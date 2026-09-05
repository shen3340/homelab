const state = {
  tags: [],
  page: 1,
  pageSize: 20,
  total: 0,
  totalPages: 1,
  search: "",
  sort: "artist",
  order: "asc",
  editingTagId: null,
  deletingTagId: null,
  provisioning: {
    tagUid: null,
    albums: [],
    selectedAlbum: null,
    source: null,
    existingTag: null,
  },
};

const elements = {
  tagsList: document.getElementById("tags-list"),
  tagSearch: document.getElementById("tag-search"),
  tagSort: document.getElementById("tag-sort"),
  tagResultsInfo: document.getElementById("tag-results-info"),
  tagPagination: document.getElementById("tag-pagination"),
  message: document.getElementById("message"),

  modal: document.getElementById("modal"),
  modalTitle: document.getElementById("modal-title"),
  wizardStep: document.getElementById("wizard-step"),

  step1: document.getElementById("step-1"),
  step2: document.getElementById("step-2"),
  step3: document.getElementById("step-3"),
  stepSuccess: document.getElementById("step-success"),
  stepEdit: document.getElementById("step-edit"),

  editTagUid: document.getElementById("edit-tag-uid"),
  editAlbum: document.getElementById("edit-album"),

  tagUid: document.getElementById("tag-uid"),
  scanButton: document.getElementById("scan-button"),
  nfcStatus: document.getElementById("nfc-status"),
  continueTagButton: document.getElementById("continue-tag-button"),

  spotifyTagUid: document.getElementById("spotify-tag-uid"),
  albumSearch: document.getElementById("album-search"),
  albumList: document.getElementById("album-list"),
  spotifyLoading: document.getElementById("spotify-loading"),
  spotifyEmpty: document.getElementById("spotify-empty"),
  spotifySearchButton: document.getElementById("spotify-search-button"),

  confirmationAlbum: document.getElementById("confirmation-album"),
  confirmationTagUid: document.getElementById("confirmation-tag-uid"),
  confirmationUrl: document.getElementById("confirmation-url"),

  successDetails: document.getElementById("success-details"),

  deleteModal: document.getElementById("delete-modal"),
  deleteDetails: document.getElementById("delete-details"),
};

function showMessage(text, type) {
  elements.message.textContent = text;
  elements.message.className = `message ${type}`;

  window.scrollTo({
    top: 0,
    behavior: "smooth",
  });

  setTimeout(() => {
    elements.message.className = "message hidden";
  }, 4000);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  let body = null;

  try {
    body = await response.json();
  } catch {
    // Response does not contain JSON.
  }

  if (!response.ok) {
    throw new Error(body?.detail || "Request failed");
  }

  return body;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

function normalizeUid(uid) {
  return uid.replace(/-/g, ":").toUpperCase();
}

function resetProvisioningState() {
  state.provisioning = {
    tagUid: null,
    albums: [],
    selectedAlbum: null,
    source: null,
    existingTag: null,
  };
}

async function loadTags() {
  elements.tagsList.innerHTML = '<div class="loading">Loading tags...</div>';

  try {
    const params = new URLSearchParams({
      page: state.page,
      page_size: state.pageSize,
      search: state.search,
      sort: state.sort,
      order: state.order,
    });

    const result = await api(`/tags?${params}`);

    state.tags = result.items;
    state.page = result.page;
    state.pageSize = result.page_size;
    state.total = result.total;
    state.totalPages = result.total_pages;

    renderTags();
    renderTagPagination();
  } catch (error) {
    elements.tagsList.innerHTML =
      '<div class="empty">Unable to load tags.</div>';
    elements.tagResultsInfo.textContent = "";
    elements.tagPagination.innerHTML = "";

    showMessage(error.message, "error");
  }
}

function renderTags() {
  if (!state.tags.length) {
    elements.tagsList.innerHTML = '<div class="empty">No NFC tags found.</div>';
    elements.tagResultsInfo.textContent = "";
    return;
  }

  const start = (state.page - 1) * state.pageSize + 1;
  const end = Math.min(start + state.tags.length - 1, state.total);

  elements.tagResultsInfo.textContent = `Showing ${start}–${end} of ${state.total} tags`;

  elements.tagsList.innerHTML = "";

  state.tags.forEach((tag) => {
    const card = document.createElement("article");
    card.className = "tag-card";

    const title = document.createElement("h3");
    title.className = "tag-name";
    title.textContent = `${tag.artist} — ${tag.title}`;

    const uid = document.createElement("p");
    uid.className = "tag-uid";
    uid.textContent = `UID: ${tag.tag_uid}`;

    const actions = document.createElement("div");
    actions.className = "tag-actions";

    const editButton = document.createElement("button");
    editButton.className = "secondary-button";
    editButton.textContent = "Edit";
    editButton.addEventListener("click", () => openEditTag(tag.id));

    const deleteButton = document.createElement("button");
    deleteButton.className = "danger-button";
    deleteButton.textContent = "Delete";
    deleteButton.addEventListener("click", () => openDeleteTag(tag.id));

    actions.append(editButton, deleteButton);
    card.append(title, uid, actions);
    elements.tagsList.appendChild(card);
  });
}

function renderTagPagination() {
  elements.tagPagination.innerHTML = "";

  if (state.totalPages <= 1) {
    return;
  }

  const createPageButton = (label, page, active = false) => {
    const button = document.createElement("button");

    button.className = `pagination-button${active ? " active" : ""}`;
    button.textContent = label;
    button.disabled = page === state.page;

    button.addEventListener("click", () => changeTagPage(page));

    return button;
  };

  elements.tagPagination.appendChild(
    createPageButton("Previous", state.page - 1),
  );

  for (let page = 1; page <= state.totalPages; page += 1) {
    elements.tagPagination.appendChild(
      createPageButton(page, page, page === state.page),
    );
  }

  elements.tagPagination.appendChild(createPageButton("Next", state.page + 1));
}

function changeTagPage(page) {
  if (page < 1 || page > state.totalPages || page === state.page) {
    return;
  }

  state.page = page;
  loadTags();

  window.scrollTo({
    top: 0,
    behavior: "smooth",
  });
}

function openAddTag() {
  state.editingTagId = null;
  resetProvisioningState();

  elements.modalTitle.textContent = "Add NFC Tag";

  elements.tagUid.value = "";
  elements.nfcStatus.textContent = "Scan a tag or enter its UID manually.";

  elements.albumSearch.value = "";
  elements.albumList.innerHTML = "";
  elements.spotifyEmpty.textContent = "No matching albums found.";
  elements.spotifyEmpty.classList.add("hidden");
  elements.spotifyLoading.classList.add("hidden");

  elements.modal.classList.remove("hidden");

  showWizardStep(1);
}

async function openEditTag(tagId) {
  const tag = state.tags.find((item) => item.id === tagId);

  if (!tag) {
    return;
  }

  state.editingTagId = tagId;

  elements.modalTitle.textContent = "Edit NFC Tag";
  elements.editTagUid.value = tag.tag_uid;
  elements.editAlbum.innerHTML = '<option value="">Loading albums...</option>';

  elements.modal.classList.remove("hidden");
  showWizardStep("edit");

  try {
    const albums = await api("/albums");

    elements.editAlbum.innerHTML = "";

    if (!albums.length) {
      elements.editAlbum.innerHTML =
        '<option value="">No albums available</option>';
      return;
    }

    albums.forEach((album) => {
      const option = document.createElement("option");

      option.value = album.id;
      option.textContent = `${album.artist} — ${album.title}`;
      option.selected = album.id === tag.album_id;

      elements.editAlbum.appendChild(option);
    });
  } catch (error) {
    elements.editAlbum.innerHTML =
      '<option value="">Unable to load albums</option>';

    showMessage(error.message, "error");
  }
}

function closeModal() {
  elements.modal.classList.add("hidden");

  state.editingTagId = null;
  resetProvisioningState();
}

function showWizardStep(step) {
  [
    elements.step1,
    elements.step2,
    elements.step3,
    elements.stepEdit,
    elements.stepSuccess,
  ].forEach((element) => element.classList.add("hidden"));

  const steps = {
    1: [elements.step1, "Step 1 of 3"],
    2: [elements.step2, "Step 2 of 3"],
    3: [elements.step3, "Step 3 of 3"],
    edit: [elements.stepEdit, "Edit Tag"],
    success: [elements.stepSuccess, "Complete"],
  };

  const selected = steps[step];

  if (!selected) {
    return;
  }

  selected[0].classList.remove("hidden");
  elements.wizardStep.textContent = selected[1];
}

async function scanNfcTag() {
  if (!("NDEFReader" in window)) {
    elements.nfcStatus.textContent =
      "Web NFC is unavailable. Enter the UID manually.";
    elements.tagUid.focus();
    return;
  }

  try {
    const ndef = new NDEFReader();

    elements.scanButton.disabled = true;
    elements.scanButton.textContent = "Waiting...";
    elements.nfcStatus.textContent = "Hold NFC tag near your phone.";

    ndef.addEventListener(
      "reading",
      ({ serialNumber }) => {
        elements.scanButton.disabled = false;
        elements.scanButton.textContent = "Scan NFC Tag";

        if (!serialNumber) {
          elements.nfcStatus.textContent =
            "Tag detected, but phone did not provide a UID.";
          return;
        }

        elements.tagUid.value = normalizeUid(serialNumber);
        elements.nfcStatus.textContent = "NFC tag detected.";
      },
      { once: true },
    );

    await ndef.scan();
  } catch {
    elements.scanButton.disabled = false;
    elements.scanButton.textContent = "Scan NFC Tag";

    elements.nfcStatus.textContent =
      "NFC scan unavailable. Enter the UID manually.";
  }
}

async function continueWithTag() {
  const tagUid = normalizeUid(elements.tagUid.value.trim());

  if (!tagUid) {
    showMessage("Enter or scan an NFC tag UID.", "error");
    return;
  }

  elements.tagUid.value = tagUid;

  state.provisioning.tagUid = tagUid;
  state.provisioning.existingTag =
    state.tags.find((tag) => tag.tag_uid.toUpperCase() === tagUid) || null;

  elements.spotifyTagUid.textContent = tagUid;
  elements.albumSearch.value = "";
  elements.albumList.innerHTML =
    '<div class="loading">Loading your albums...</div>';

  elements.spotifyEmpty.classList.add("hidden");
  elements.spotifyLoading.classList.add("hidden");

  showWizardStep(2);

  try {
    state.provisioning.albums = await api("/albums/available");
    renderExistingAlbums();
  } catch (error) {
    elements.albumList.innerHTML =
      '<div class="empty">Unable to load your albums.</div>';

    showMessage(error.message, "error");
  }

  elements.albumSearch.focus();
}

function createAlbumOption(album, onSelect, includeArtwork = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "album-option";

  if (includeArtwork && album.image_url) {
    const image = document.createElement("img");

    image.className = "album-art";
    image.src = album.image_url;
    image.alt = "";

    button.appendChild(image);
  }

  const content = document.createElement("span");
  content.className = "album-option-content";

  const title = document.createElement("strong");
  title.textContent = album.title;

  const artist = document.createElement("span");
  artist.textContent = album.artist;

  const meta = document.createElement("span");
  meta.className = "album-meta";

  content.append(title, artist, meta);
  button.appendChild(content);

  meta.textContent = "Existing album";

  button.addEventListener("click", onSelect);

  return button;
}

function renderExistingAlbums(albums = state.provisioning.albums) {
  elements.albumList.innerHTML = "";

  if (!albums.length) {
    elements.albumList.innerHTML =
      '<div class="empty">No albums have been added yet.</div>';
    return;
  }

  elements.spotifyEmpty.classList.add("hidden");

  albums.forEach((album) => {
    elements.albumList.appendChild(
      createAlbumOption(album, () => selectAlbum(album, "database")),
    );
  });
}

function filterExistingAlbums() {
  const query = elements.albumSearch.value.trim().toLowerCase();

  if (!query) {
    renderExistingAlbums();
    return;
  }

  const albums = state.provisioning.albums.filter((album) => {
    const title = (album.title || "").toLowerCase();
    const artist = (album.artist || "").toLowerCase();

    return title.includes(query) || artist.includes(query);
  });

  if (!albums.length) {
    elements.albumList.innerHTML =
      '<div class="empty">No matching albums in your library.</div>';
    return;
  }

  renderExistingAlbums(albums);
}

function selectAlbum(album, source) {
  state.provisioning.selectedAlbum = album;
  state.provisioning.source = source;

  renderConfirmation();
  showWizardStep(3);
}

async function searchSpotify() {
  const query = elements.albumSearch.value.trim();

  if (!query) {
    showMessage("Enter an artist or album to search Spotify.", "error");
    return;
  }

  elements.spotifyLoading.textContent = "Searching Spotify...";
  elements.spotifyLoading.classList.remove("hidden");
  elements.spotifyEmpty.classList.add("hidden");
  elements.albumList.innerHTML = "";

  try {
    const results = await api(`/spotify/search?q=${encodeURIComponent(query)}`);

    renderSpotifyResults(results);
  } catch (error) {
    elements.spotifyEmpty.textContent =
      error.message || "Spotify search failed.";
    elements.spotifyEmpty.classList.remove("hidden");
  } finally {
    elements.spotifyLoading.classList.add("hidden");
  }
}

function renderSpotifyResults(results) {
  elements.albumList.innerHTML = "";

  if (!results.length) {
    elements.spotifyEmpty.textContent = "No matching albums found.";
    elements.spotifyEmpty.classList.remove("hidden");
    return;
  }

  elements.spotifyEmpty.classList.add("hidden");

  results.forEach((album) => {
    const button = createAlbumOption(
      album,
      () => selectAlbum(album, "spotify"),
      true,
    );

    const meta = button.querySelector(".album-meta");

    meta.textContent = `${album.release_year || ""}${
      album.explicit !== undefined
        ? album.explicit
          ? " • Explicit"
          : " • Clean"
        : ""
    }`;

    elements.albumList.appendChild(button);
  });
}

function renderConfirmation() {
  const { selectedAlbum: album, tagUid, source } = state.provisioning;

  if (!album || !tagUid) {
    return;
  }

  const playbackUrl = `https://music.shen3340.com/t/${encodeURIComponent(tagUid)}`;

  const sourceMessage =
    source === "database"
      ? "Existing album — no new album will be created."
      : "Spotify album — this album will be added to your library.";

  elements.confirmationAlbum.innerHTML = "";

  if (album.image_url) {
    const image = document.createElement("img");

    image.className = "confirmation-art";
    image.src = album.image_url;
    image.alt = "";

    elements.confirmationAlbum.appendChild(image);
  }

  const details = document.createElement("div");

  const title = document.createElement("strong");
  title.textContent = album.title;

  const artist = document.createElement("span");
  artist.textContent = album.artist;

  details.append(title, artist);

  if (album.release_year || album.explicit !== undefined) {
    const metadata = document.createElement("span");

    metadata.textContent = `${album.release_year || ""}${
      album.explicit !== undefined
        ? album.explicit
          ? " • Explicit"
          : " • Clean"
        : ""
    }`;

    details.appendChild(metadata);
  }

  const sourceText = document.createElement("span");
  sourceText.className = "help-text";
  sourceText.textContent = sourceMessage;

  details.appendChild(sourceText);
  elements.confirmationAlbum.appendChild(details);

  elements.confirmationTagUid.textContent = tagUid;
  elements.confirmationUrl.textContent = playbackUrl;
}

async function confirmProvisioning() {
  const {
    selectedAlbum: album,
    tagUid,
    source,
    existingTag,
  } = state.provisioning;

  if (!album || !tagUid) {
    showMessage("Select an album and NFC tag first.", "error");
    return;
  }

  const button = document.getElementById("confirm-button");

  button.disabled = true;
  button.textContent = "Hold tag near phone...";

  const playbackUrl = `https://music.shen3340.com/t/${encodeURIComponent(tagUid)}`;

  try {
    if (!("NDEFReader" in window)) {
      throw new Error("NDEFReader is unavailable in this browser.");
    }

    showMessage("Hold the NFC tag near your phone...", "success");

    const ndef = new NDEFReader();

    await ndef.write({
      records: [
        {
          recordType: "url",
          data: playbackUrl,
        },
      ],
    });

    button.textContent = "Configuring...";

    showMessage("NFC tag written. Configuring database...", "success");

    let albumRecord;

    if (source === "database") {
      albumRecord = album;
    } else {
      const existingAlbum = await findExistingAlbum(album.spotify_id);

      albumRecord =
        existingAlbum ||
        (await api("/albums", {
          method: "POST",
          body: JSON.stringify({
            spotify_id: album.spotify_id,
          }),
        }));
    }

    if (existingTag) {
      await api(`/tags/${existingTag.id}`, {
        method: "PUT",
        body: JSON.stringify({
          tag_uid: tagUid,
          album_id: albumRecord.id,
        }),
      });
    } else {
      await api("/tags", {
        method: "POST",
        body: JSON.stringify({
          tag_uid: tagUid,
          album_id: albumRecord.id,
        }),
      });
    }

    elements.successDetails.innerHTML = `
  <p>
    <strong>
      ${escapeHtml(albumRecord.artist)}
      —
      ${escapeHtml(albumRecord.title)}
    </strong>
  </p>

  <p>
    UID:
    <code>${escapeHtml(tagUid)}</code>
  </p>

  <p>
    NFC:
    <strong>Written ✓</strong>
  </p>

  <p>
    Database:
    <strong>Configured ✓</strong>
  </p>
`;

    await loadTags();

    showWizardStep("success");
  } catch (error) {
    showMessage(
      `NFC ERROR: ${error.name || "Unknown"} — ${
        error.message || "Unable to write NFC tag."
      }`,
      "error",
    );

    button.disabled = false;
    button.textContent = "Write & Configure";
  }
}

async function findExistingAlbum(spotifyId) {
  try {
    const albums = await api("/albums");

    return albums.find((album) => album.spotify_id === spotifyId) || null;
  } catch {
    return null;
  }
}

async function saveTagEdit() {
  if (!state.editingTagId) {
    return;
  }

  const albumId = Number(elements.editAlbum.value);

  if (!albumId) {
    showMessage("Select an album.", "error");
    return;
  }

  const button = document.getElementById("save-edit-button");

  button.disabled = true;
  button.textContent = "Saving...";

  try {
    await api(`/tags/${state.editingTagId}`, {
      method: "PUT",
      body: JSON.stringify({
        tag_uid: elements.editTagUid.value,
        album_id: albumId,
      }),
    });

    closeModal();

    showMessage("NFC tag updated.", "success");

    await loadTags();
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Save Changes";
  }
}

function openDeleteTag(tagId) {
  const tag = state.tags.find((item) => item.id === tagId);

  if (!tag) {
    return;
  }

  state.deletingTagId = tagId;

  elements.deleteDetails.innerHTML = "";

  const title = document.createElement("strong");
  title.textContent = `${tag.artist} — ${tag.title}`;

  const lineBreak = document.createElement("br");

  const uid = document.createElement("code");
  uid.textContent = tag.tag_uid;

  elements.deleteDetails.append(title, lineBreak, uid);
  elements.deleteModal.classList.remove("hidden");
}

function closeDeleteModal() {
  elements.deleteModal.classList.add("hidden");
  state.deletingTagId = null;
}

async function deleteTag() {
  if (!state.deletingTagId) {
    return;
  }

  const button = document.getElementById("confirm-delete-button");

  button.disabled = true;
  button.textContent = "Deleting...";

  try {
    await api(`/tags/${state.deletingTagId}`, {
      method: "DELETE",
    });

    closeDeleteModal();

    showMessage("NFC tag deleted.", "success");

    await loadTags();
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "Delete";
  }
}

function initializeAdmin() {
  document
    .getElementById("add-tag-button")
    .addEventListener("click", openAddTag);

  document.getElementById("refresh-button").addEventListener("click", loadTags);

  document
    .getElementById("close-modal-button")
    .addEventListener("click", closeModal);

  document
    .getElementById("cancel-button")
    .addEventListener("click", closeModal);

  document.getElementById("scan-button").addEventListener("click", scanNfcTag);

  document
    .getElementById("continue-tag-button")
    .addEventListener("click", continueWithTag);

  document
    .getElementById("back-to-tag-button")
    .addEventListener("click", () => {
      showWizardStep(1);
    });

  document
    .getElementById("back-to-search-button")
    .addEventListener("click", () => {
      showWizardStep(2);
    });

  document
    .getElementById("confirm-button")
    .addEventListener("click", confirmProvisioning);

  document.getElementById("done-button").addEventListener("click", closeModal);

  elements.albumSearch.addEventListener("input", filterExistingAlbums);

  elements.spotifySearchButton.addEventListener("click", searchSpotify);

  document
    .getElementById("cancel-delete-button")
    .addEventListener("click", closeDeleteModal);

  document
    .getElementById("confirm-delete-button")
    .addEventListener("click", deleteTag);

  document
    .getElementById("cancel-edit-button")
    .addEventListener("click", closeModal);

  document
    .getElementById("save-edit-button")
    .addEventListener("click", saveTagEdit);

  elements.modal
    .querySelector(".modal-backdrop")
    .addEventListener("click", closeModal);

  elements.deleteModal
    .querySelector(".modal-backdrop")
    .addEventListener("click", closeDeleteModal);

  let tagSearchTimeout;

  elements.tagSearch.addEventListener("input", () => {
    clearTimeout(tagSearchTimeout);

    tagSearchTimeout = setTimeout(() => {
      state.search = elements.tagSearch.value.trim();
      state.page = 1;

      loadTags();
    }, 300);
  });

  elements.tagSort.addEventListener("change", () => {
    const [sort, order] = elements.tagSort.value.split("-");

    state.sort = sort;
    state.order = order;
    state.page = 1;

    loadTags();
  });

  loadTags();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeAdmin, {
    once: true,
  });
} else {
  initializeAdmin();
}
