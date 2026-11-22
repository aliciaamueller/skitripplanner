// One trip, for organisers. Registrations come from Trip Management and
// rooms from Room Allocation; this page is the only place the two meet.

const tripId = Number(new URLSearchParams(location.search).get("id"));

async function showTrip() {
    // Rooms come from the other service. If Room Allocation is down, the
    // trip and its registrations still show, with a notice instead of rooms.
    const roomData = Promise.all([
        api(`${ROOMS}/trips/${tripId}/rooms`),
        api(`${ROOMS}/trips/${tripId}/assignments`),
        api(`${ROOMS}/trips/${tripId}/preferences`),
    ]).catch(() => null);

    const [trip, registrations, roomResults] = await Promise.all([
        api(`${TRIPS}/trips/${tripId}`),
        api(`${TRIPS}/trips/${tripId}/registrations`),
        roomData,
    ]);
    const [rooms, assignments, preferences] = roomResults ?? [[], [], []];
    if (roomResults === null) {
        showMessage("Rooms are unavailable right now, so they are not shown. Registrations and payments still work.", "error");
    }

    // Look up names and rooms by registration ID.
    const names = Object.fromEntries(registrations.map((r) => [r.id, r.name]));
    const roomOf = Object.fromEntries(assignments.map((a) => [a.registration_id, a.room_name]));
    const confirmed = registrations.filter((r) => r.status === "confirmed");
    const withoutRoom = confirmed.filter((r) => !roomOf[r.id]);

    document.title = `${trip.name} · Ski Club`;
    document.getElementById("trip-name").textContent = trip.name;
    document.getElementById("trip-where").textContent =
        `${trip.destination} · ${formatDates(trip.start_date, trip.end_date)}`;

    const freeRooms = rooms.filter((room) => room.occupied < room.capacity);

    showStats(trip.stats, confirmed.length - withoutRoom.length, withoutRoom.length);
    showRegistrations(registrations, roomOf, freeRooms, roomResults !== null);
    showRooms(rooms, withoutRoom, assignments, names);
    showPreferences(confirmed, preferences, names);
}

function showStats(stats, roomed, needRoom) {
    const stat = (label, value, extra = "") =>
        `<div class="stat ${extra}"><span>${label}</span><strong>${value}</strong></div>`;

    document.getElementById("stats").innerHTML =
        stat("Places free", stats.places_remaining, "highlight") +
        stat("Paid", stats.confirmed) +
        stat("Waiting to pay", stats.pending_payment) +
        stat("Waiting list", stats.waitlisted) +
        stat("Have a room", roomed) +
        stat("Need a room", needRoom);
}

// What the Room column shows: the room, a picker for a paid student without
// one, or a short reason why there is nothing to pick.
function roomCell(registration, roomOf, freeRooms, roomsAvailable) {
    if (roomOf[registration.id]) {
        return escapeHtml(roomOf[registration.id]);
    }
    if (registration.status !== "confirmed" || !roomsAvailable) {
        return `<span class="muted">—</span>`;
    }
    if (freeRooms.length === 0) {
        return `<span class="muted">No free beds, add a room</span>`;
    }
    return `<select class="inline" aria-label="Room for ${escapeHtml(registration.name)}"
                    onchange="assignRoom(this.value, ${registration.id})">
        <option value="">Choose a room…</option>
        ${freeRooms.map((room) => `<option value="${room.id}">${escapeHtml(room.name)}
            (${room.capacity - room.occupied} free)</option>`).join("")}
    </select>`;
}

// Names by registration number, for the messages after Mark paid and Cancel.
let nameOf = {};

function showRegistrations(registrations, roomOf, freeRooms, roomsAvailable) {
    nameOf = Object.fromEntries(registrations.map((r) => [r.id, r.name]));
    document.getElementById("registration-count").textContent =
        plural(registrations.length, "registration");

    if (registrations.length === 0) {
        document.getElementById("registrations").innerHTML =
            `<tr><td colspan="6" class="muted">No one has registered yet.</td></tr>`;
        return;
    }

    document.getElementById("registrations").innerHTML = registrations.map((r) => `
        <tr>
            <td class="muted">#${r.id}</td>
            <td><strong>${escapeHtml(r.name)}</strong></td>
            <td>${escapeHtml(r.email)}</td>
            <td>
                <span class="pill ${r.status}">${statusLabel(r.status)}</span>
                ${r.status === "pending_payment" && r.payment_deadline
                    ? `<span class="hint">Pay by ${formatDateTime(r.payment_deadline)}</span>` : ""}
            </td>
            <td>${roomCell(r, roomOf, freeRooms, roomsAvailable)}</td>
            <td class="actions"><div>
                ${r.status === "pending_payment"
                    ? `<button class="small" onclick="act('payment', ${r.id}, 'Payment recorded for ')">Mark paid</button>` : ""}
                ${r.status !== "cancelled"
                    ? `<button class="small danger" onclick="cancelRegistration(${r.id})">Cancel</button>` : ""}
            </div></td>
        </tr>
    `).join("");
}

function showRooms(rooms, withoutRoom, assignments, names) {
    document.getElementById("need-room").textContent = withoutRoom.length === 0
        ? "Every paid student has a room"
        : `${plural(withoutRoom.length, "paid student")} still without a room`;

    document.getElementById("rooms").innerHTML = rooms.length === 0
        ? `<div class="empty">No rooms yet. Add the first one below.</div>`
        : rooms.map((room) => {
            const sleepers = assignments.filter((a) => a.room_id === room.id);
            const freeBeds = room.capacity - sleepers.length;
            return `
            <div class="panel">
                <div class="section-heading">
                    <h3>${escapeHtml(room.name)}</h3>
                    <span class="pill confirmed">${room.occupied}/${room.capacity} beds</span>
                </div>
                <div class="bar"><div style="width: ${room.occupied / room.capacity * 100}%"></div></div>
                <ul class="occupants">
                    ${sleepers.map((a) => `<li>🛏 ${escapeHtml(names[a.registration_id] || `#${a.registration_id}`)}</li>`).join("")}
                    ${freeBeds > 0 ? `<li class="free">${plural(freeBeds, "free bed")}</li>` : ""}
                </ul>
            </div>`;
        }).join("");
}

function showPreferences(confirmed, preferences, names) {
    for (const select of document.querySelectorAll(".confirmed-students")) {
        fillSelect(select, confirmed, "Choose a student");
    }

    document.getElementById("preferences").innerHTML = preferences.length === 0
        ? `<li class="muted">No requests yet.</li>`
        : preferences.map((p) => `
            <li><strong>${escapeHtml(names[p.registration_id])}</strong> wants to share with
                <strong>${escapeHtml(names[p.preferred_registration_id])}</strong></li>
        `).join("");
}

function fillSelect(select, items, placeholder) {
    select.innerHTML = `<option value="">${placeholder}</option>` + items.map(
        (item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`
    ).join("");
}

// The "Mark paid" and "Cancel" buttons in the table.
async function act(action, registrationId, success) {
    const name = nameOf[registrationId];
    try {
        await api(`${TRIPS}/registrations/${registrationId}/${action}`, {});
        await showTrip();
        showMessage(`${success}${name}.`, "success");
    } catch (error) {
        showMessage(error.message, "error");
    }
}

// Cancelling cannot be undone, so ask first.
function cancelRegistration(registrationId) {
    const sure = confirm(`Cancel ${nameOf[registrationId]}'s registration?\n\n`
        + "Their place goes to the next person on the waiting list and their bed is freed. "
        + "This cannot be undone.");
    if (sure) {
        act("cancel", registrationId, "Registration cancelled for ");
    }
}

// Picking a room in a student's row assigns them straight away.
async function assignRoom(roomId, registrationId) {
    if (!roomId) {
        return;
    }
    try {
        await api(`${ROOMS}/rooms/${roomId}/assignments`, { registration_id: registrationId });
        await showTrip();
        showMessage("Room assigned.", "success");
    } catch (error) {
        showMessage(error.message, "error");
    }
}

onSubmit(document.getElementById("register"), async (values) => {
    const { id } = await api(`${TRIPS}/trips/${tripId}/registrations`, values);
    await showTrip();
    return `${values.name} is registered with number #${id}.`;
});

onSubmit(document.getElementById("create-room"), async (values) => {
    await api(`${ROOMS}/trips/${tripId}/rooms`, { ...values, capacity: Number(values.capacity) });
    await showTrip();
    return `${values.name} added.`;
});

onSubmit(document.getElementById("preference"), async (values) => {
    await api(`${ROOMS}/preferences`, {
        registration_id: Number(values.registration_id),
        preferred_registration_id: Number(values.preferred_registration_id),
    });
    await showTrip();
    return "Roommate request saved.";
});

showTrip().catch((error) => showMessage(error.message, "error"));
