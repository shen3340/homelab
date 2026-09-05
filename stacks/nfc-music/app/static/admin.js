const state = {
  tags: [],
  editingTagId: null,
  deletingTagId: null,

  provisioning: {
    tagUid: null,
    existingAlbums: [],
    spotifyResults: [],
    selectedAlbum: null,
    selectedAlbumSource: null,
    existingTag: null,
  },
};

const elements = {
  tagsList: document.getElementById("tags-list"),
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
  editEnabled: document.getElementById("edit-enabled"),

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
    body = null;
  }

  if (!response.ok) {
    const detail = body?.detail || "Request failed";
    throw new Error(detail);
  }

  return body;
}

async function loadTags() {
  elements.tagsList.innerHTML = '<div class="loading">Loading tags...</div>';

  try {
    state.tags = await api("/admin/tags");
    renderTags();
  } catch (error) {
    elements.tagsList.innerHTML =
      '<div class="empty">Unable to load tags.</div>';

    showMessage(error.message, "error");
  }
}

function renderTags() {
  if (!state.tags.length) {
    elements.tagsList.innerHTML =
      '<div class="empty">No NFC tags registered yet.</div>';
    return;
  }

  elements.tagsList.innerHTML = state.tags
    .map((tag) => {
      const enabled = tag.enabled === true;

      return `
        <article class="tag-card">
          <h3 class="tag-name">
            ${escapeHtml(tag.artist)} — ${escapeHtml(tag.title)}
          </h3>

          <p class="tag-uid">
            UID: ${escapeHtml(tag.tag_uid)}
          </p>

          <span class="tag-status ${
            enabled ? "status-enabled" : "status-disabled"
          }">
            ${enabled ? "Enabled" : "Disabled"}
          </span>

          <div class="tag-actions">
            <button
              class="secondary-button"
              onclick="openEditTag(${tag.id})"
            >
              Edit
            </button>

            <button
              class="danger-button"
              onclick="openDeleteTag(${tag.id})"
            >
              Delete
            </button>
          </div>
        </article>
      `;
    })
    .join("");
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

function resetProvisioningState() {
  state.provisioning = {
    tagUid: null,
    existingAlbums: [],
    spotifyResults: [],
    selectedAlbum: null,
    selectedAlbumSource: null,
    existingTag: null,
  };
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
  elements.wizardStep.textContent = "Edit Tag";

  elements.editTagUid.value = tag.tag_uid;
  elements.editEnabled.checked = tag.enabled === true;

  elements.editAlbum.innerHTML = '<option value="">Loading albums...</option>';

  elements.modal.classList.remove("hidden");

  showWizardStep("edit");

  try {
    const albums = await api("/admin/albums");

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

      if (album.id === tag.album_id) {
        option.selected = true;
      }

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
  elements.step1.classList.add("hidden");
  elements.step2.classList.add("hidden");
  elements.step3.classList.add("hidden");
  elements.stepEdit.classList.add("hidden");
  elements.stepSuccess.classList.add("hidden");

  if (step === 1) {
    elements.step1.classList.remove("hidden");
    elements.wizardStep.textContent = "Step 1 of 3";
  }

  if (step === 2) {
    elements.step2.classList.remove("hidden");
    elements.wizardStep.textContent = "Step 2 of 3";
  }

  if (step === 3) {
    elements.step3.classList.remove("hidden");
    elements.wizardStep.textContent = "Step 3 of 3";
  }

  if (step === "edit") {
    elements.stepEdit.classList.remove("hidden");
    elements.wizardStep.textContent = "Edit Tag";
  }

  if (step === "success") {
    elements.stepSuccess.classList.remove("hidden");
    elements.wizardStep.textContent = "Complete";
  }
}

function normalizeUid(uid) {
  return uid.replace(/-/g, ":").toUpperCase();
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

async function writeNfcTag(url) {
  if (!("NDEFReader" in window)) {
    throw new Error(
      "Web NFC is unavailable on this device. NFC writing cannot be performed.",
    );
  }

  const ndef = new NDEFReader();

  await ndef.write({
    records: [
      {
        recordType: "url",
        data: url,
      },
    ],
  });
}

async function continueWithTag() {
  const tagUid = normalizeUid(elements.tagUid.value.trim());

  if (!tagUid) {
    showMessage("Enter or scan an NFC tag UID.", "error");
    return;
  }

  elements.tagUid.value = tagUid;

  state.provisioning.tagUid = tagUid;

  const existingTag = state.tags.find(
    (tag) => tag.tag_uid.toUpperCase() === tagUid,
  );

  state.provisioning.existingTag = existingTag || null;

  elements.spotifyTagUid.textContent = tagUid;

  elements.albumSearch.value = "";
  elements.albumList.innerHTML =
    '<div class="loading">Loading your albums...</div>';

  elements.spotifyEmpty.classList.add("hidden");
  elements.spotifyLoading.classList.add("hidden");

  showWizardStep(2);

  try {
    const albums = await api("/admin/albums");

    state.provisioning.existingAlbums = albums;

    renderExistingAlbums();
  } catch (error) {
    elements.albumList.innerHTML =
      '<div class="empty">Unable to load your albums.</div>';

    showMessage(error.message, "error");
  }

  elements.albumSearch.focus();
}

function renderExistingAlbums() {
  const albums = state.provisioning.existingAlbums;

  if (!albums.length) {
    elements.albumList.innerHTML =
      '<div class="empty">No albums have been added yet.</div>';

    return;
  }

  elements.spotifyEmpty.classList.add("hidden");

  elements.albumList.innerHTML = albums
    .map(
      (album, index) => `
        <button
          type="button"
          class="album-option"
          onclick="selectExistingAlbum(${index})"
        >
          <span class="album-option-content">
            <strong>
              ${escapeHtml(album.title)}
            </strong>

            <span>
              ${escapeHtml(album.artist)}
            </span>

            <span class="album-meta">
              Existing album
            </span>
          </span>
        </button>
      `,
    )
    .join("");
}

function filterExistingAlbums() {
  const query = elements.albumSearch.value.trim().toLowerCase();

  const albums = state.provisioning.existingAlbums;

  if (!query) {
    renderExistingAlbums();
    return;
  }

  const filtered = albums.filter((album) => {
    const title = (album.title || "").toLowerCase();
    const artist = (album.artist || "").toLowerCase();

    return title.includes(query) || artist.includes(query);
  });

  if (!filtered.length) {
    elements.albumList.innerHTML =
      '<div class="empty">No matching albums in your library.</div>';

    return;
  }

  elements.spotifyEmpty.classList.add("hidden");

  elements.albumList.innerHTML = filtered
    .map((album) => {
      const originalIndex = albums.indexOf(album);

      return `
        <button
          type="button"
          class="album-option"
          onclick="selectExistingAlbum(${originalIndex})"
        >
          <span class="album-option-content">
            <strong>
              ${escapeHtml(album.title)}
            </strong>

            <span>
              ${escapeHtml(album.artist)}
            </span>

            <span class="album-meta">
              Existing album
            </span>
          </span>
        </button>
      `;
    })
    .join("");
}

function selectExistingAlbum(index) {
  const album = state.provisioning.existingAlbums[index];

  if (!album) {
    return;
  }

  state.provisioning.selectedAlbum = album;
  state.provisioning.selectedAlbumSource = "database";

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
    const results = await api(
      `/admin/spotify/search?q=${encodeURIComponent(query)}`,
    );

    state.provisioning.spotifyResults = results;

    renderSpotifyResults();
  } catch (error) {
    elements.spotifyEmpty.textContent =
      error.message || "Spotify search failed.";

    elements.spotifyEmpty.classList.remove("hidden");
  } finally {
    elements.spotifyLoading.classList.add("hidden");
  }
}

function renderSpotifyResults() {
  const results = state.provisioning.spotifyResults;

  if (!results.length) {
    elements.spotifyEmpty.textContent = "No matching albums found.";

    elements.spotifyEmpty.classList.remove("hidden");

    return;
  }

  elements.spotifyEmpty.classList.add("hidden");

  elements.albumList.innerHTML = results
    .map(
      (album, index) => `
        <button
          type="button"
          class="album-option"
          onclick="selectSpotifyAlbum(${index})"
        >
          ${
            album.image_url
              ? `
                <img
                  class="album-art"
                  src="${escapeHtml(album.image_url)}"
                  alt=""
                />
              `
              : ""
          }

          <span class="album-option-content">
            <strong>
              ${escapeHtml(album.title)}
            </strong>

            <span>
              ${escapeHtml(album.artist)}
            </span>

            <span class="album-meta">
              ${escapeHtml(album.release_year || "")}
              ${album.explicit ? " • Explicit" : " • Clean"}
            </span>
          </span>
        </button>
      `,
    )
    .join("");
}

function selectSpotifyAlbum(index) {
  const album = state.provisioning.spotifyResults[index];

  if (!album) {
    return;
  }

  state.provisioning.selectedAlbum = album;
  state.provisioning.selectedAlbumSource = "spotify";

  renderConfirmation();

  showWizardStep(3);
}

function renderConfirmation() {
  const album = state.provisioning.selectedAlbum;
  const tagUid = state.provisioning.tagUid;
  const source = state.provisioning.selectedAlbumSource;

  if (!album || !tagUid) {
    return;
  }

  const playbackUrl = `${window.location.origin}/t/${encodeURIComponent(tagUid)}`;

  const sourceMessage =
    source === "database"
      ? "Existing album — no new album will be created."
      : "Spotify album — this album will be added to your library.";

  elements.confirmationAlbum.innerHTML = `
    ${
      album.image_url
        ? `
          <img
            class="confirmation-art"
            src="${escapeHtml(album.image_url)}"
            alt=""
          />
        `
        : ""
    }

    <div>
      <strong>
        ${escapeHtml(album.title)}
      </strong>

      <span>
        ${escapeHtml(album.artist)}
      </span>

      ${
        album.release_year || album.explicit !== undefined
          ? `
            <span>
              ${escapeHtml(album.release_year || "")}
              ${
                album.explicit !== undefined
                  ? album.explicit
                    ? " • Explicit"
                    : " • Clean"
                  : ""
              }
            </span>
          `
          : ""
      }

      <span class="help-text">
        ${sourceMessage}
      </span>
    </div>
  `;

  elements.confirmationTagUid.textContent = tagUid;
  elements.confirmationUrl.textContent = playbackUrl;
}

async function confirmProvisioning() {
  const album = state.provisioning.selectedAlbum;
  const tagUid = state.provisioning.tagUid;
  const source = state.provisioning.selectedAlbumSource;

  if (!album || !tagUid) {
    showMessage("Select an album and NFC tag first.", "error");
    return;
  }

  const button = document.getElementById("confirm-button");

  button.disabled = true;
  button.textContent = "Hold tag near phone...";

  const playbackUrl = `${window.location.origin}/t/${encodeURIComponent(tagUid)}`;

  try {
    if (!("NDEFReader" in window)) {
      throw new Error("NDEFReader is unavailable in this browser.");
    }

    showMessage("Hold the NFC tag near your phone...", "success");

    console.log("Starting NFC write:", playbackUrl);

    const ndef = new NDEFReader();

    await ndef.write({
      records: [
        {
          recordType: "url",
          data: playbackUrl,
        },
      ],
    });

    console.log("NFC write completed");

    // NFC is finished. The user should no longer need to interact
    // with the button.
    button.disabled = true;
    button.textContent = "Configuring...";
    showMessage("NFC tag written. Configuring database...", "success");

    let albumRecord;

    if (source === "database") {
      // The album already exists in PostgreSQL.
      albumRecord = album;

      console.log("Using existing album:", albumRecord.id);
    } else {
      // Album came from Spotify.
      // Check whether it already exists before creating it.
      const existingAlbum = await findExistingAlbum(album.spotify_id);

      if (existingAlbum) {
        albumRecord = existingAlbum;
      } else {
        albumRecord = await api("/admin/albums", {
          method: "POST",
          body: JSON.stringify({
            spotify_id: album.spotify_id,
          }),
        });
      }

      console.log("Using Spotify album:", albumRecord.id);
    }

    const existingTag = state.provisioning.existingTag;

    if (existingTag) {
      console.log("Updating existing tag:", existingTag.id);

      await api(`/admin/tags/${existingTag.id}`, {
        method: "PUT",
        body: JSON.stringify({
          tag_uid: tagUid,
          album_id: albumRecord.id,
          enabled: true,
        }),
      });
    } else {
      console.log("Creating new tag");

      await api("/admin/tags", {
        method: "POST",
        body: JSON.stringify({
          tag_uid: tagUid,
          album_id: albumRecord.id,
        }),
      });
    }

    console.log("Database configuration completed");

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
    console.error("NFC provisioning failed:", error);

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
    const albums = await api("/admin/albums");

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
    await api(`/admin/tags/${state.editingTagId}`, {
      method: "PUT",
      body: JSON.stringify({
        tag_uid: elements.editTagUid.value,
        album_id: albumId,
        enabled: elements.editEnabled.checked,
      }),
    });

    showMessage("NFC tag updated.", "success");

    state.editingTagId = null;

    closeModal();

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

  elements.deleteDetails.innerHTML = `
    <strong>
      ${escapeHtml(tag.artist)} — ${escapeHtml(tag.title)}
    </strong>

    <br>

    <code>
      ${escapeHtml(tag.tag_uid)}
    </code>
  `;

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
    await api(`/admin/tags/${state.deletingTagId}`, {
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

  elements.albumSearch.addEventListener("input", () => {
    filterExistingAlbums();
  });

  elements.spotifySearchButton.addEventListener("click", searchSpotify);

  document
    .getElementById("cancel-delete-button")
    .addEventListener("click", closeDeleteModal);

  document
    .getElementById("confirm-delete-button")
    .addEventListener("click", deleteTag);

  const modalBackdrop = elements.modal.querySelector(".modal-backdrop");

  modalBackdrop.addEventListener("click", closeModal);

  const deleteModalBackdrop =
    elements.deleteModal.querySelector(".modal-backdrop");

  deleteModalBackdrop.addEventListener("click", closeDeleteModal);

  document
    .getElementById("cancel-edit-button")
    .addEventListener("click", closeModal);

  document
    .getElementById("save-edit-button")
    .addEventListener("click", saveTagEdit);

  loadTags();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeAdmin);
} else {
  initializeAdmin();
}
