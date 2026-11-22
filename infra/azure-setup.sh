#!/usr/bin/env bash
# One-time Azure setup (Assignment 2, §7). Run once, by hand, signed in with
# `az login` and `gh auth login`. After this, only the pipeline changes Azure:
# it creates and updates the two Container Apps and uploads the UI.
#
#   LOCATION=<one of your allowed regions> PROFESSOR=<professor's email> ./infra/azure-setup.sh
#
# Every password is generated here and stored only as a GitHub Actions secret;
# none is printed or written to a file. Safe to re-run: each step skips what
# already exists (passwords are only set when a resource is first created).
set -euo pipefail

PREFIX=amueller-ieu2024
REPO=aliciaamueller/skitripplanner
LOCATION=${LOCATION:?set LOCATION to one of your allowed regions}
RG=rg-$PREFIX
IDENTITY=$PREFIX-github
SQL_SERVER=$PREFIX-sql
TRIPS_DB=$PREFIX-trip-management-db
ROOMS_DB=$PREFIX-room-allocation-db
STORAGE=amuellerieu2024ui
ENVIRONMENT=$PREFIX-env

password() { echo "Pw-$(openssl rand -hex 16)"; }
exists() { "$@" >/dev/null 2>&1; }

echo "== Providers and the containerapp CLI extension"
az extension add --name containerapp --upgrade --yes --only-show-errors
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Sql Microsoft.Storage Microsoft.ManagedIdentity; do
  az provider register --namespace "$ns" --wait
done

echo "== Resource group $RG in $LOCATION"
az group create --name "$RG" --location "$LOCATION" --output none

echo "== Managed identity $IDENTITY, trusted only for runs on main of $REPO"
az identity create --resource-group "$RG" --name "$IDENTITY" --output none
CLIENT_ID=$(az identity show -g "$RG" -n "$IDENTITY" --query clientId -o tsv)
PRINCIPAL_ID=$(az identity show -g "$RG" -n "$IDENTITY" --query principalId -o tsv)
exists az identity federated-credential show -g "$RG" --identity-name "$IDENTITY" --name github-main ||
  az identity federated-credential create -g "$RG" --identity-name "$IDENTITY" --name github-main \
    --issuer https://token.actions.githubusercontent.com \
    --subject "repo:$REPO:ref:refs/heads/main" \
    --audiences api://AzureADTokenExchange --output none
RG_ID=$(az group show --name "$RG" --query id -o tsv)
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role Contributor --scope "$RG_ID" --output none

echo "== SQL server $SQL_SERVER and two serverless databases (free offer)"
if ! exists az sql server show -g "$RG" -n "$SQL_SERVER"; then
  SQL_ADMIN_PASSWORD=$(password)
  az sql server create -g "$RG" -n "$SQL_SERVER" -l "$LOCATION" \
    --admin-user sqladmin --admin-password "$SQL_ADMIN_PASSWORD" --output none
  # Kept only as a GitHub secret, for running this script's user step again.
  gh secret set SQL_ADMIN_PASSWORD --repo "$REPO" --body "$SQL_ADMIN_PASSWORD"
fi
# 0.0.0.0 is Azure's rule for "allow Azure services" (the Container Apps).
az sql server firewall-rule create -g "$RG" -s "$SQL_SERVER" -n AllowAzureServices \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 --output none
for db in "$TRIPS_DB" "$ROOMS_DB"; do
  exists az sql db show -g "$RG" -s "$SQL_SERVER" -n "$db" ||
    az sql db create -g "$RG" -s "$SQL_SERVER" -n "$db" \
      --edition GeneralPurpose --compute-model Serverless --family Gen5 \
      --capacity 1 --min-capacity 0.5 --auto-pause-delay 60 --max-size 32GB \
      --backup-storage-redundancy Local \
      --use-free-limit --free-limit-exhaustion-behavior AutoPause --output none
done

echo "== One login per service, each a user in its own database only"
# Contained database users: trips_app exists only in the trip-management
# database and rooms_app only in the room-allocation one, so neither can
# open the other database. Needs this machine's IP in the firewall for a
# moment, and the admin password, which only exists if the server was just
# created; on a re-run, set SQL_ADMIN_PASSWORD yourself to repeat this step.
if [ -n "${SQL_ADMIN_PASSWORD:-}" ]; then
  MY_IP=$(curl -s https://api.ipify.org)
  az sql server firewall-rule create -g "$RG" -s "$SQL_SERVER" -n setup-machine \
    --start-ip-address "$MY_IP" --end-ip-address "$MY_IP" --output none
  TRIPS_PASSWORD=$(password)
  ROOMS_PASSWORD=$(password)
  run_sql() {  # database, SQL
    docker run --rm mcr.microsoft.com/mssql/server:2022-latest /opt/mssql-tools18/bin/sqlcmd \
      -S "tcp:$SQL_SERVER.database.windows.net,1433" -d "$1" -U sqladmin -P "$SQL_ADMIN_PASSWORD" \
      -b -l 60 -Q "$2"
  }
  run_sql "$TRIPS_DB" "IF USER_ID('trips_app') IS NULL CREATE USER trips_app WITH PASSWORD = '$TRIPS_PASSWORD'; ELSE ALTER USER trips_app WITH PASSWORD = '$TRIPS_PASSWORD'; ALTER ROLE db_owner ADD MEMBER trips_app;"
  run_sql "$ROOMS_DB" "IF USER_ID('rooms_app') IS NULL CREATE USER rooms_app WITH PASSWORD = '$ROOMS_PASSWORD'; ELSE ALTER USER rooms_app WITH PASSWORD = '$ROOMS_PASSWORD'; ALTER ROLE db_owner ADD MEMBER rooms_app;"
  az sql server firewall-rule delete -g "$RG" -s "$SQL_SERVER" -n setup-machine --output none
  HOST=$SQL_SERVER.database.windows.net
  gh secret set TRIPS_DATABASE_URL --repo "$REPO" --body "mssql://trips_app:$TRIPS_PASSWORD@$HOST:1433/$TRIPS_DB"
  gh secret set ROOMS_DATABASE_URL --repo "$REPO" --body "mssql://rooms_app:$ROOMS_PASSWORD@$HOST:1433/$ROOMS_DB"
fi

echo "== Storage account $STORAGE with a static website"
exists az storage account show -g "$RG" -n "$STORAGE" ||
  az storage account create -g "$RG" -n "$STORAGE" -l "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --allow-blob-public-access false --output none
az storage blob service-properties update --account-name "$STORAGE" --auth-mode key \
  --static-website --index-document index.html --404-document index.html --output none

echo "== Container Apps environment $ENVIRONMENT (creates its Log Analytics workspace)"
exists az containerapp env show -g "$RG" -n "$ENVIRONMENT" ||
  az containerapp env create -g "$RG" -n "$ENVIRONMENT" -l "$LOCATION" --output none

echo "== GitHub secrets the pipeline signs in with (IDs, not passwords)"
gh secret set AZURE_CLIENT_ID --repo "$REPO" --body "$CLIENT_ID"
gh secret set AZURE_TENANT_ID --repo "$REPO" --body "$(az account show --query tenantId -o tsv)"
gh secret set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$(az account show --query id -o tsv)"

if [ -n "${PROFESSOR:-}" ]; then
  echo "== Reader role on $RG for $PROFESSOR"
  az role assignment create --assignee "$PROFESSOR" --role Reader --scope "$RG_ID" --output none
fi

echo "Done. UI address: $(az storage account show -g "$RG" -n "$STORAGE" --query primaryEndpoints.web -o tsv)"
