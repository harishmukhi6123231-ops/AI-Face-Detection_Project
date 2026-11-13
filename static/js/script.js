const input = document.getElementById('image');
const preview = document.getElementById('preview');
const dropText = document.getElementById('dropText');
const dropZone = document.getElementById('dropZone');

function showFile(file) {
  if (!file || !file.type.startsWith('image/')) return;
  dropText.textContent = file.name;
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
  document.getElementById('uploadEmpty').hidden = true;
}

input?.addEventListener('change', () => showFile(input.files[0]));
dropZone?.addEventListener('dragover', (event) => {
  event.preventDefault();
  dropZone.classList.add('dragging');
});
dropZone?.addEventListener('dragleave', () => dropZone.classList.remove('dragging'));
dropZone?.addEventListener('drop', (event) => {
  event.preventDefault();
  dropZone.classList.remove('dragging');
  const file = event.dataTransfer.files[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  showFile(file);
});

const video = document.getElementById('cameraVideo');
const overlay = document.getElementById('cameraOverlay');
const startButton = document.getElementById('startCamera');
const stopButton = document.getElementById('stopCamera');
const cameraStatus = document.getElementById('cameraStatus');
const cameraPlaceholder = document.getElementById('cameraPlaceholder');
const recognitionCard = document.getElementById('recognitionCard');
const registrationPanel = document.getElementById('registrationPanel');
const registrationStatus = document.getElementById('registrationStatus');
let cameraStream = null;
let scanTimer = null;
let lastFrame = null;
let registrationFrame = null;
let scanInProgress = false;
let completingPersonKey = null;

function captureFrame() {
  if (!video.videoWidth) return null;
  const canvas = document.createElement('canvas');
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  return canvas.toDataURL('image/jpeg', 0.82);
}

function drawFaces(data) {
  const context = overlay.getContext('2d');
  overlay.width = data.width;
  overlay.height = data.height;
  context.clearRect(0, 0, overlay.width, overlay.height);
  data.faces.forEach((face) => {
    const [x1, y1, x2, y2] = face.bbox;
    // The video is mirrored with CSS. Mirror only the box coordinates so text stays readable.
    const mirroredLeft = overlay.width - x2;
    const mirroredRight = overlay.width - x1;
    context.strokeStyle = face.liveness_status === 'fake' || face.liveness_status === 'unavailable'
      ? '#ff7584'
      : face.liveness_status === 'input_rejected'
        ? '#ffc889'
        : face.name === 'Unknown'
          ? '#ffbd78'
          : getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
    context.lineWidth = Math.max(2, overlay.width / 400);
    context.strokeRect(mirroredLeft, y1, mirroredRight - mirroredLeft, y2 - y1);
    context.font = `bold ${Math.max(16, overlay.width / 40)}px sans-serif`;
    context.fillStyle = context.strokeStyle;
    context.fillText(face.name, mirroredLeft, Math.max(22, y1 - 8));
  });
  const incompleteFace = data.faces.find((face) => face.needs_details);
  const detailsPrompt = document.getElementById('detailsPrompt');
  detailsPrompt.hidden = !incompleteFace;
  if (incompleteFace) {
    document.getElementById('detailsPromptName').textContent = incompleteFace.name;
    document.getElementById('completeDetails').dataset.personKey = incompleteFace.person_key;
    document.getElementById('completeDetails').dataset.personName = incompleteFace.name;
  }
  cameraStatus.textContent = data.faces.length
    ? data.faces.map((face) => {
        if (face.liveness_status === 'fake') return 'Photo or screen image suspected — attendance not recorded.';
        if (face.liveness_status === 'input_rejected') return 'Liveness could not be checked — center your face and move slightly closer.';
        if (face.liveness_status === 'unavailable') return 'Liveness check unavailable — attendance not recorded.';
        if (face.name === 'Unknown') return 'Unknown person — register from the right panel.';
        if (face.needs_details) return `${face.name} · details required before attendance`;
        return `${face.name}${face.checked_in ? ' · attendance recorded' : ' · already checked in today'}`;
      }).join(' · ')
    : 'No face detected — face the camera and improve the lighting.';
}

async function scanFrame() {
  if (scanInProgress || !cameraStream) return;
  const frame = captureFrame();
  if (!frame) return;
  scanInProgress = true;
  lastFrame = frame;
  try {
    const response = await fetch('/camera/recognize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: frame, mark_attendance: true }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Face scan failed.');
    drawFaces(data);
  } catch (error) {
    cameraStatus.textContent = error.message;
  } finally {
    scanInProgress = false;
  }
}

async function startCamera() {
  if (cameraStream) return;
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false });
    video.srcObject = cameraStream;
    video.hidden = false;
    overlay.hidden = false;
    cameraPlaceholder.hidden = true;
    startButton.hidden = true;
    stopButton.hidden = false;
    cameraStatus.textContent = 'Camera is on. Scanning for faces…';
    if (!registrationPanel.hidden) registrationStatus.textContent = 'Camera is on. Center one face in the left preview.';
    await video.play();
    scanFrame();
    scanTimer = window.setInterval(scanFrame, 1800);
  } catch (error) {
    const message = error.name === 'NotAllowedError'
      ? 'Camera access was blocked. Allow camera access in your browser settings, then try again.'
      : 'Could not start the camera. Check that a camera is connected and available.';
    cameraStatus.textContent = message;
    if (!registrationPanel.hidden) registrationStatus.textContent = message;
  }
}

startButton?.addEventListener('click', startCamera);

document.getElementById('registerNew')?.addEventListener('click', () => {
  recognitionCard.hidden = true;
  registrationPanel.hidden = false;
  completingPersonKey = null;
  const form = document.getElementById('registrationForm');
  form.reset();
  form.hidden = true;
  document.getElementById('personName').readOnly = false;
  document.getElementById('captureStep').hidden = false;
  document.getElementById('registrationSnapshot').hidden = true;
  registrationFrame = null;
  registrationStatus.textContent = cameraStream
    ? 'Camera is on. Capture one face before entering details.'
    : 'Starting camera… allow access when your browser asks.';
  if (!cameraStream) startCamera();
});

document.getElementById('captureFaceButton')?.addEventListener('click', async (event) => {
  if (!cameraStream || !video.videoWidth) {
    registrationStatus.textContent = 'Wait for the camera preview to start, then capture the face.';
    return;
  }
  const capturedFrame = captureFrame();
  if (!capturedFrame) {
    registrationStatus.textContent = 'Could not capture a camera frame. Try again.';
    return;
  }
  const captureButton = event.currentTarget;
  captureButton.disabled = true;
  registrationStatus.textContent = 'Checking the captured frame for exactly one face…';
  try {
    const response = await fetch('/camera/recognize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: capturedFrame, mark_attendance: false }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not check the captured face.');
    if (data.faces.length !== 1) {
      registrationStatus.textContent = 'Please capture a clear frame with exactly one face, then try again.';
      return;
    }
    if (data.faces[0].liveness_status !== 'live') {
      registrationStatus.textContent = data.faces[0].liveness_status === 'input_rejected'
        ? 'Liveness check needs a clearer view. Center the face and move a little closer.'
        : 'The camera did not verify a live person. Use the camera directly and try again.';
      return;
    }
    registrationFrame = capturedFrame;
  } catch (error) {
    registrationStatus.textContent = error.message;
    return;
  } finally {
    captureButton.disabled = false;
  }
  document.getElementById('registrationSnapshot').src = registrationFrame;
  document.getElementById('registrationSnapshot').hidden = false;
  document.getElementById('captureStep').hidden = true;
  document.getElementById('registrationForm').hidden = false;
  registrationStatus.textContent = 'Face captured. Enter the person’s details to finish registration.';
  document.getElementById('personName').focus();
});

document.getElementById('retakeFace')?.addEventListener('click', () => {
  registrationFrame = null;
  document.getElementById('registrationForm').hidden = true;
  document.getElementById('captureStep').hidden = false;
  document.getElementById('registrationSnapshot').hidden = true;
  registrationStatus.textContent = 'Center one face in the left preview and capture again.';
});

document.getElementById('backToRecognition')?.addEventListener('click', () => {
  registrationPanel.hidden = true;
  recognitionCard.hidden = false;
  completingPersonKey = null;
  document.getElementById('personName').readOnly = false;
  document.getElementById('saveRegistration').textContent = 'Save registration';
});

document.getElementById('completeDetails')?.addEventListener('click', (event) => {
  const button = event.currentTarget;
  completingPersonKey = Number(button.dataset.personKey);
  recognitionCard.hidden = true;
  registrationPanel.hidden = false;
  document.getElementById('captureStep').hidden = true;
  const form = document.getElementById('registrationForm');
  form.reset();
  form.hidden = false;
  document.getElementById('personName').value = button.dataset.personName;
  document.getElementById('personName').readOnly = true;
  document.getElementById('saveRegistration').textContent = 'Save details and check in';
  document.getElementById('registrationSnapshot').hidden = true;
  registrationStatus.textContent = 'This person is already registered from a photo. Add the missing details; no new face capture is needed.';
  document.getElementById('personId').focus();
});

stopButton?.addEventListener('click', () => {
  window.clearInterval(scanTimer);
  scanTimer = null;
  cameraStream?.getTracks().forEach((track) => track.stop());
  cameraStream = null;
  lastFrame = null;
  registrationFrame = null;
  video.srcObject = null;
  video.hidden = true;
  overlay.hidden = true;
  cameraPlaceholder.hidden = false;
  startButton.hidden = false;
  stopButton.hidden = true;
  cameraStatus.textContent = 'Camera stopped.';
  if (!registrationPanel.hidden) registrationStatus.textContent = 'Camera stopped. Reopen the camera to capture a face.';
});

document.getElementById('registrationForm')?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const fields = {
    name: document.getElementById('personName').value.trim(),
    person_id: document.getElementById('personId').value.trim(),
    branch_course: document.getElementById('branchCourse').value.trim(),
    contact: document.getElementById('personContact').value.trim(),
  };
  if (completingPersonKey === null && !registrationFrame) {
    registrationStatus.textContent = 'Capture a face first, then enter the person’s details.';
    return;
  }
  registrationStatus.textContent = 'Saving details and face…';
  const submitButton = document.getElementById('saveRegistration');
  submitButton.disabled = true;
  try {
    const response = completingPersonKey !== null
      ? await fetch(`/people/${completingPersonKey}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fields),
        })
      : await fetch('/camera/register', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...fields, image: registrationFrame }),
        });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Registration failed.');
    registrationStatus.textContent = data.message;
    event.currentTarget.reset();
    registrationFrame = null;
    completingPersonKey = null;
    document.getElementById('personName').readOnly = false;
    submitButton.textContent = 'Save registration';
    document.getElementById('registrationSnapshot').hidden = true;
    document.getElementById('registrationForm').hidden = true;
    document.getElementById('captureStep').hidden = false;
  } catch (error) {
    registrationStatus.textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
});

document.getElementById('checkAttendance')?.addEventListener('click', async () => {
  const panel = document.getElementById('attendanceResults');
  const list = document.getElementById('attendanceList');
  panel.hidden = false;
  list.innerHTML = '<li class="empty-attendance">Loading attendance…</li>';
  try {
    const response = await fetch('/attendance');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load attendance.');
    list.replaceChildren();
    if (!data.records.length) {
      const empty = document.createElement('li');
      empty.className = 'empty-attendance';
      empty.textContent = 'No attendance records yet.';
      list.append(empty);
    } else {
      data.records.forEach((record) => {
        const item = document.createElement('li');
        const name = document.createElement('span');
        const date = document.createElement('span');
        const time = document.createElement('time');
        const remove = document.createElement('button');
        name.textContent = record.name;
        date.textContent = record.date;
        time.textContent = record.time;
        remove.type = 'button';
        remove.className = 'delete-attendance';
        remove.dataset.deleteAttendance = record.id;
        remove.textContent = 'Delete';
        item.append(name, date, time, remove);
        list.append(item);
      });
    }
  } catch (error) {
    list.innerHTML = '';
    const item = document.createElement('li');
    item.className = 'empty-attendance';
    item.textContent = error.message;
    list.append(item);
  }
});

document.getElementById('attendanceList')?.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-delete-attendance]');
  if (!button || !window.confirm('Delete this attendance record?')) return;
  const response = await fetch(`/attendance/${button.dataset.deleteAttendance}`, { method: 'DELETE' });
  const data = await response.json();
  if (!response.ok) {
    window.alert(data.error || 'Could not delete the record.');
    return;
  }
  document.getElementById('checkAttendance').click();
});

document.getElementById('clearAttendance')?.addEventListener('click', async () => {
  if (!window.confirm('Delete all attendance records? This cannot be undone.')) return;
  const response = await fetch('/attendance', { method: 'DELETE' });
  const data = await response.json();
  if (!response.ok) {
    window.alert(data.error || 'Could not clear attendance history.');
    return;
  }
  document.getElementById('checkAttendance').click();
});

const pageTitle = document.getElementById('pageTitle');
const pageDescription = document.getElementById('pageDescription');
const dashboardGrid = document.querySelector('.dashboard-grid');
const peopleRegistry = document.getElementById('peopleRegistry');
const peopleContainer = document.getElementById('registeredPeopleList');
const defaultTitle = pageTitle.textContent;
const defaultDescription = pageDescription.textContent;

function switchView(view) {
  const showPeople = view === 'people';
  dashboardGrid.hidden = showPeople;
  peopleRegistry.hidden = !showPeople;
  pageTitle.textContent = showPeople ? 'Registered people' : defaultTitle;
  pageDescription.textContent = showPeople ? 'View captured face images and manage each person’s details.' : defaultDescription;
  document.getElementById('dashboardNav').classList.toggle('active', !showPeople);
  document.getElementById('peopleNav').classList.toggle('active', showPeople);
  if (showPeople) loadPeople();
}

document.getElementById('dashboardNav')?.addEventListener('click', () => switchView('dashboard'));
document.getElementById('peopleNav')?.addEventListener('click', () => switchView('people'));
document.getElementById('registryBack')?.addEventListener('click', () => switchView('dashboard'));

function makeProfileField(form, labelText, key, value, maxLength) {
  const label = document.createElement('label');
  const input = document.createElement('input');
  input.name = key;
  input.value = value || '';
  input.maxLength = maxLength;
  input.required = true;
  label.textContent = labelText;
  form.append(label, input);
}

async function loadPeople() {
  peopleContainer.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'empty-attendance';
  loading.textContent = 'Loading registered people…';
  peopleContainer.append(loading);
  try {
    const response = await fetch('/people');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not load registered people.');
    peopleContainer.replaceChildren();
    if (!data.people.length) {
      const empty = document.createElement('p');
      empty.className = 'empty-attendance';
      empty.textContent = 'No people have been registered yet.';
      peopleContainer.append(empty);
      return;
    }
    data.people.forEach((person) => renderPerson(person));
  } catch (error) {
    peopleContainer.replaceChildren();
    const message = document.createElement('p');
    message.className = 'empty-attendance';
    message.textContent = error.message;
    peopleContainer.append(message);
  }
}

function renderPerson(person) {
  const card = document.createElement('article');
  card.className = 'person-card';
  if (person.image_url) {
    const image = document.createElement('img');
    image.src = person.image_url;
    image.alt = `Captured face for ${person.name}`;
    image.className = 'person-photo';
    card.append(image);
  } else {
    const image = document.createElement('div');
    image.className = 'person-photo photo-missing';
    image.textContent = 'No saved face image';
    card.append(image);
  }
  const heading = document.createElement('h3');
  heading.textContent = person.name;
  card.append(heading);
  if (!person.details_complete) {
    const badge = document.createElement('p');
    badge.className = 'details-needed-badge';
    badge.textContent = 'Details needed before attendance';
    card.append(badge);
  }
  const detailList = document.createElement('dl');
  for (const [label, value] of [['ID', person.person_id], ['Branch / Course', person.branch_course], ['Contact', person.contact]]) {
    const row = document.createElement('div');
    const term = document.createElement('dt');
    const description = document.createElement('dd');
    term.textContent = label;
    description.textContent = value || 'Not provided';
    row.append(term, description);
    detailList.append(row);
  }
  card.append(detailList);
  const actions = document.createElement('div');
  actions.className = 'person-actions';
  const edit = document.createElement('button');
  edit.type = 'button'; edit.className = 'button secondary'; edit.textContent = 'Edit details';
  const remove = document.createElement('button');
  remove.type = 'button'; remove.className = 'button delete-person'; remove.textContent = 'Delete';
  edit.addEventListener('click', () => editPerson(person, card));
  remove.addEventListener('click', async () => {
    if (!window.confirm(`Delete ${person.name}, their captured face image, and associated attendance records?`)) return;
    const response = await fetch(`/people/${person.id}`, { method: 'DELETE' });
    const data = await response.json();
    if (!response.ok) { window.alert(data.error || 'Could not delete this person.'); return; }
    loadPeople();
  });
  actions.append(edit, remove);
  card.append(actions);
  peopleContainer.append(card);
}

function editPerson(person, card) {
  card.replaceChildren();
  const heading = document.createElement('h3');
  heading.textContent = `Edit ${person.name}`;
  const form = document.createElement('form');
  form.className = 'person-edit-form';
  makeProfileField(form, 'Name', 'name', person.name, 80);
  makeProfileField(form, 'ID', 'person_id', person.person_id, 50);
  makeProfileField(form, 'Branch / Course', 'branch_course', person.branch_course, 100);
  makeProfileField(form, 'Contact', 'contact', person.contact, 30);
  const actions = document.createElement('div');
  actions.className = 'person-actions';
  const save = document.createElement('button');
  save.className = 'button primary'; save.type = 'submit'; save.textContent = 'Save changes';
  const cancel = document.createElement('button');
  cancel.className = 'button secondary'; cancel.type = 'button'; cancel.textContent = 'Cancel';
  cancel.addEventListener('click', () => renderPerson(person));
  actions.append(save, cancel);
  form.append(actions);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const details = Object.fromEntries(new FormData(form).entries());
    const response = await fetch(`/people/${person.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(details),
    });
    const data = await response.json();
    if (!response.ok) { window.alert(data.error || 'Could not update this person.'); return; }
    loadPeople();
  });
  card.append(heading, form);
}

const themeRoot = document.documentElement;
const themeTrigger = document.getElementById('themeTrigger');
const themeMenu = document.getElementById('themeMenu');
const themeChoices = [...document.querySelectorAll('[data-theme-choice]')];

function applyTheme(theme) {
  const validThemes = ['crimson', 'sky', 'dark'];
  const selected = validThemes.includes(theme) ? theme : 'dark';
  themeRoot.dataset.theme = selected;
  try { localStorage.setItem('face-finder-theme', selected); } catch (_) {}
  themeChoices.forEach((button) => {
    const active = button.dataset.themeChoice === selected;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

let savedTheme = 'dark';
try { savedTheme = localStorage.getItem('face-finder-theme') || 'dark'; } catch (_) {}
applyTheme(savedTheme);

themeTrigger?.addEventListener('click', () => {
  const opening = themeMenu.hidden;
  themeMenu.hidden = !opening;
  themeTrigger.setAttribute('aria-expanded', String(opening));
});
themeChoices.forEach((button) => button.addEventListener('click', () => {
  applyTheme(button.dataset.themeChoice);
  themeMenu.hidden = true;
  themeTrigger.setAttribute('aria-expanded', 'false');
}));
document.addEventListener('click', (event) => {
  if (!event.target.closest('.theme-section') && themeMenu && !themeMenu.hidden) {
    themeMenu.hidden = true;
    themeTrigger.setAttribute('aria-expanded', 'false');
  }
});
