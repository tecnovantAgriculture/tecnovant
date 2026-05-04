/**
 * crud.js — Generic CRUD operations for entity-based management pages.
 *
 * Requires window.CRUD_CONFIG to be set by the including template with:
 *   - entityName       (string)  e.g. "User"
 *   - entityNameLower  (string)  e.g. "user"
 *   - apiUrl           (string)  e.g. "/api/v1/core/users/"
 *   - items            (array)   initial data for form pre-fill
 *   - formFields       (object)  field definitions with allowedNewValue flags
 *   - csvUploadUrl     (string|null)
 *   - csvDownloadUrl   (string|null)
 *   - showSelectBox    (bool)
 *   - showViewButton   (bool)
 *
 * Usage in template:
 *   <script>window.CRUD_CONFIG = { ... }; </script>
 *   <script src="/js/crud.js"></script>
 */
(function () {
    'use strict';

    /* ------------------------------------------------------------------ */
    /*  Config retrieval                                                    */
    /* ------------------------------------------------------------------ */
    var CFG = window.CRUD_CONFIG || {};
    var entityName = CFG.entityName || 'Entity';
    var entityNameLower = CFG.entityNameLower || 'entity';
    var apiUrl = CFG.apiUrl || '';
    var items = CFG.items || [];
    var formFields = CFG.formFields || {};
    var csvUploadUrl = CFG.csvUploadUrl || null;
    var csvDownloadUrl = CFG.csvDownloadUrl || null;
    var showSelectBox = CFG.showSelectBox !== undefined ? CFG.showSelectBox : true;
    var showViewButton = CFG.showViewButton !== undefined ? CFG.showViewButton : false;

    /* ------------------------------------------------------------------ */
    /*  State                                                               */
    /* ------------------------------------------------------------------ */
    var currentAction = '';
    var currentEntityId = null;
    var activeDropdown = null;

    /* ------------------------------------------------------------------ */
    /*  Helpers                                                             */
    /* ------------------------------------------------------------------ */

    /**
     * Get CSRF token — prefers global getCsrfToken(), falls back to getCookie().
     * @returns {string}
     */
    function getCsrf() {
        if (typeof window.getCsrfToken === 'function') {
            return window.getCsrfToken();
        }
        if (typeof getCookie === 'function') {
            return getCookie('csrf_access_token');
        }
        return '';
    }

    /**
     * Legacy getCookie fallback (for pages that may still use it).
     * @param {string} name
     * @returns {string|null}
     */
    function getCookie(name) {
        var cookieValue = null;
        var nameEQ = name + '=';
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i];
            while (cookie.charAt(0) === ' ') {
                cookie = cookie.substring(1, cookie.length);
            }
            if (cookie.indexOf(nameEQ) === 0) {
                cookieValue = decodeURIComponent(cookie.substring(nameEQ.length));
                break;
            }
        }
        return cookieValue;
    }

    /* ------------------------------------------------------------------ */
    /*  Dropdown                                                            */
    /* ------------------------------------------------------------------ */

    /**
     * Toggle visibility of an action dropdown.
     * @param {string} id
     */
    function toggleDropdown(id) {
        var dropdown = document.getElementById('dropdown-' + id);
        if (!dropdown) return;
        var allDropdowns = document.querySelectorAll('.origin-top-right');
        allDropdowns.forEach(function (d) {
            if (d !== dropdown) d.classList.add('hidden');
        });
        dropdown.classList.toggle('hidden');
        var isOpen = !dropdown.classList.contains('hidden');
        var btn = document.getElementById('options-menu-' + id);
        if (btn) btn.setAttribute('aria-expanded', isOpen);
        activeDropdown = isOpen ? dropdown : null;

        if (isOpen) {
            var firstItem = dropdown.querySelector('[role="menuitem"]');
            if (firstItem) firstItem.focus();
        }
    }

    /**
     * Keyboard navigation for dropdowns.
     * @param {KeyboardEvent} event
     * @param {string} id
     */
    function handleDropdownKey(event, id) {
        var dropdown = document.getElementById('dropdown-' + id);
        if (!dropdown) return;
        var isOpen = !dropdown.classList.contains('hidden');
        var itemsList = Array.from(dropdown.querySelectorAll('[role="menuitem"]'));
        var currentIndex = itemsList.indexOf(document.activeElement);

        if (event.key === 'ArrowDown') {
            event.preventDefault();
            if (!isOpen) toggleDropdown(id);
            var next = currentIndex < itemsList.length - 1 ? currentIndex + 1 : 0;
            if (itemsList[next]) itemsList[next].focus();
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            if (!isOpen) { toggleDropdown(id); return; }
            var prev = currentIndex > 0 ? currentIndex - 1 : itemsList.length - 1;
            if (itemsList[prev]) itemsList[prev].focus();
        } else if (event.key === 'Escape') {
            if (isOpen) {
                toggleDropdown(id);
                var btn = document.getElementById('options-menu-' + id);
                if (btn) btn.focus();
            }
        } else if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            toggleDropdown(id);
        }
    }

    /**
     * Close all dropdowns when clicking outside.
     */
    function windowOnClick(event) {
        if (!event.target.closest('.origin-top-right') && !event.target.matches('[aria-haspopup="true"]')) {
            document.querySelectorAll('.origin-top-right').forEach(function (dropdown) {
                dropdown.classList.add('hidden');
            });
            activeDropdown = null;
        }
    }

    /* ------------------------------------------------------------------ */
    /*  Modal management                                                    */
    /* ------------------------------------------------------------------ */

    /**
     * Show a modal (create / edit / view / delete).
     * @param {string} action
     * @param {string|null} id
     */
    function showModal(action, id) {
        currentAction = action;
        currentEntityId = id;
        var modal = document.getElementById(entityNameLower + 'Modal');
        var form = document.getElementById(entityNameLower + 'Form');
        var title = document.getElementById(entityNameLower + 'ModalLabel');
        var saveButton = document.getElementById('saveButton');

        if (!modal || !form) return;

        form.reset();

        // Enable all fields first
        var inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(function (input) {
            input.disabled = false;
        });

        switch (action) {
            case 'create':
                title.textContent = 'Crear Nuevo ' + entityName;
                if (saveButton) saveButton.style.display = 'inline-flex';
                break;
            case 'edit':
                title.textContent = 'Editar ' + entityName;
                if (saveButton) saveButton.style.display = 'inline-flex';
                fillFormWithData(id);
                disableFieldsInEdit();
                break;
            case 'view':
                title.textContent = 'Ver ' + entityName;
                if (saveButton) saveButton.style.display = 'none';
                fillFormWithData(id);
                disableAllFields();
                break;
            case 'delete':
                var deleteModal = document.getElementById('deleteModal');
                if (deleteModal) deleteModal.classList.remove('hidden');
                return;
        }
        modal.classList.remove('hidden');
    }

    /**
     * Close the main modal.
     */
    function closeModal() {
        var modal = document.getElementById(entityNameLower + 'Modal');
        if (modal) modal.classList.add('hidden');
    }

    /**
     * Close the delete confirmation modal.
     */
    function closeDeleteModal() {
        var modal = document.getElementById('deleteModal');
        if (modal) modal.classList.add('hidden');
    }

    /**
     * Click-outside-to-close handler for modals.
     */
    function handleModalOutsideClick(event) {
        var modals = [
            document.getElementById(entityNameLower + 'Modal'),
            document.getElementById('deleteModal')
        ];

        modals.forEach(function (modal) {
            if (modal && !modal.classList.contains('hidden')) {
                var modalContent = modal.querySelector('.inline-block');
                if (modalContent && !modalContent.contains(event.target) && modal.contains(event.target)) {
                    if (modal.id === entityNameLower + 'Modal') {
                        closeModal();
                    } else if (modal.id === 'deleteModal') {
                        closeDeleteModal();
                    }
                }
            }
        });
    }

    /* ------------------------------------------------------------------ */
    /*  Form helpers                                                        */
    /* ------------------------------------------------------------------ */

    /**
     * Fill form fields with data from a matching item.
     * @param {string|number} id
     */
    function fillFormWithData(id) {
        var item = items.find(function (f) { return String(f.id) === String(id); });
        if (!item) return;

        var idField = document.getElementById(entityNameLower + 'Id');
        if (idField) idField.value = item.id;

        Object.keys(formFields).forEach(function (fieldName) {
            var fieldInfo = formFields[fieldName];
            var el = document.getElementById(fieldName);
            if (!el) return;

            if (fieldInfo.type === 'select') {
                el.value = item[fieldName] || '';
            } else if (fieldInfo.type === 'checkbox') {
                el.checked = item[fieldName] === true || item[fieldName] === 'true';
            } else if (fieldInfo.type === 'radio') {
                var radioValue = item[fieldName];
                if (radioValue) {
                    var radio = document.querySelector('input[name="' + fieldName + '"][value="' + radioValue + '"]');
                    if (radio) radio.checked = true;
                }
            }
            // file/image fields cannot be pre-filled
            else if (fieldInfo.type !== 'file' && fieldInfo.type !== 'image') {
                el.value = item[fieldName] || '';
            }
        });
    }

    /**
     * Disable fields marked disabled_in_edit when action is 'edit'.
     */
    function disableFieldsInEdit() {
        Object.keys(formFields).forEach(function (fieldName) {
            var fieldInfo = formFields[fieldName];
            if (fieldInfo.disabled_in_edit) {
                var el = document.getElementById(fieldName);
                if (el) el.disabled = currentAction === 'edit';
            }
        });
    }

    /**
     * Disable all form fields for view mode.
     */
    function disableAllFields() {
        if (currentAction !== 'view') return;
        var form = document.getElementById(entityNameLower + 'Form');
        if (!form) return;
        var inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(function (input) {
            input.disabled = true;
        });
    }

    /**
     * Handle "other" option in select fields with custom input.
     * @param {HTMLSelectElement} select
     * @param {string} fieldId
     */
    function handleSelectChange(select, fieldId) {
        var customInput = document.getElementById(fieldId + '_custom');
        if (!customInput) return;
        if (select.value === 'other') {
            customInput.classList.remove('hidden');
            customInput.disabled = false;
        } else {
            customInput.classList.add('hidden');
            customInput.disabled = true;
            customInput.value = '';
        }
    }

    /* ------------------------------------------------------------------ */
    /*  CRUD operations                                                     */
    /* ------------------------------------------------------------------ */

    /**
     * Build the form data object from current form fields.
     * @returns {object}
     */
    function buildFormData() {
        var data = {};
        Object.keys(formFields).forEach(function (fieldName) {
            var fieldInfo = formFields[fieldName];
            if (fieldInfo.type === 'checkbox') {
                var el = document.getElementById(fieldName);
                data[fieldName] = el ? el.checked : false;
            } else if (fieldInfo.type === 'select') {
                var selectEl = document.getElementById(fieldName);
                var selectValue = selectEl ? selectEl.value : '';
                var customInput = document.getElementById(fieldName + '_custom');
                if (fieldInfo.allowedNewValue && selectValue === 'other' && customInput && !customInput.disabled) {
                    data[fieldName] = customInput.value;
                } else {
                    data[fieldName] = selectValue;
                }
            } else if (fieldInfo.type === 'radio') {
                var checkedRadio = document.querySelector('input[name="' + fieldName + '"]:checked');
                data[fieldName] = checkedRadio ? checkedRadio.value : '';
            } else if (fieldInfo.type === 'file' || fieldInfo.type === 'image') {
                var fileEl = document.getElementById(fieldName);
                data[fieldName] = (fileEl && fileEl.files && fileEl.files[0]) ? fileEl.files[0] : null;
            } else {
                var inputEl = document.getElementById(fieldName);
                data[fieldName] = inputEl ? inputEl.value : '';
            }
        });
        return data;
    }

    /**
     * Check if form has file/image fields.
     * @returns {boolean}
     */
    function hasFileFields() {
        return Object.keys(formFields).some(function (fieldName) {
            var t = formFields[fieldName].type;
            return t === 'file' || t === 'image';
        });
    }

    /**
     * Save or update an entity.
     */
    async function saveEntity() {
        var data = buildFormData();
        var url = apiUrl;
        var method = 'POST';

        if (currentAction === 'edit') {
            method = 'PUT';
            data.id = currentEntityId;
            url = apiUrl + String(currentEntityId);
        }

        var hasFiles = hasFileFields() && data[Object.keys(formFields).find(function (k) {
            return formFields[k].type === 'file' || formFields[k].type === 'image';
        })] !== null;

        try {
            var response;
            if (hasFiles) {
                var formData = new FormData();
                for (var key in data) {
                    if (data[key] !== null) {
                        formData.append(key, data[key]);
                    }
                }
                response = await fetch(url, {
                    method: method,
                    credentials: 'include',
                    headers: { 'X-CSRF-TOKEN': getCsrf() },
                    body: formData
                });
            } else {
                response = await fetch(url, {
                    method: method,
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-TOKEN': getCsrf()
                    },
                    body: JSON.stringify(data)
                });
            }

            if (response.ok) {
                location.reload();
            } else {
                alert('Error al guardar el ' + entityNameLower);
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Error al guardar el ' + entityNameLower);
        }
    }

    /**
     * Delete an entity.
     */
    async function deleteEntity() {
        var url = apiUrl + String(currentEntityId);
        var method = 'DELETE';
        try {
            var response = await fetch(url, {
                method: method,
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-TOKEN': getCsrf()
                },
                body: JSON.stringify({ id: String(currentEntityId) })
            });

            if (response.ok) {
                location.reload();
            } else {
                alert('Error al eliminar el ' + entityNameLower);
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Error al eliminar el ' + entityNameLower);
        }
    }

    /* ------------------------------------------------------------------ */
    /*  Bulk operations                                                     */
    /* ------------------------------------------------------------------ */

    /**
     * Toggle select-all checkboxes.
     */
    function toggleSelectAll() {
        var checkboxes = document.querySelectorAll('.item-checkbox');
        var selectAll = document.getElementById('select-all');
        var checked = selectAll ? selectAll.checked : false;
        checkboxes.forEach(function (checkbox) {
            checkbox.checked = checked;
        });
    }

    /**
     * Handle bulk delete of selected items.
     */
    async function handleBulkAction() {
        var selectedItems = Array.from(document.querySelectorAll('.item-checkbox:checked'))
            .map(function (cb) { return cb.value; });

        if (selectedItems.length === 0) {
            alert('Por favor seleccione al menos un elemento.');
            return;
        }
        if (!confirm('¿Está seguro de que desea eliminar los elementos seleccionados?')) return;

        try {
            var response = await fetch(apiUrl, {
                method: 'DELETE',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-TOKEN': getCsrf()
                },
                body: JSON.stringify({ ids: selectedItems })
            });

            if (response.ok) {
                location.reload();
            } else {
                alert('Error al eliminar los elementos seleccionados');
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Error al eliminar los elementos seleccionados');
        }
    }

    /* ------------------------------------------------------------------ */
    /*  CSV operations                                                      */
    /* ------------------------------------------------------------------ */

    /**
     * Upload a CSV file.
     */
    async function uploadCsv() {
        if (!csvUploadUrl) {
            alert('La subida de CSV no está habilitada.');
            return;
        }
        var input = document.getElementById('csv-file-input');
        if (!input || !input.files.length) {
            alert('Seleccione un archivo CSV');
            return;
        }
        var formData = new FormData();
        formData.append('file', input.files[0]);
        try {
            var response = await fetch(csvUploadUrl, {
                method: 'POST',
                credentials: 'include',
                headers: { 'X-CSRF-TOKEN': getCsrf() },
                body: formData
            });
            if (response.ok) {
                location.reload();
            } else {
                var data = await response.json();
                alert(data.error || 'Error al subir el CSV');
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Error al subir el CSV');
        }
    }

    /* ------------------------------------------------------------------ */
    /*  Global exposure                                                     */
    /* ------------------------------------------------------------------ */

    // Expose functions for inline onclick handlers
    window.toggleDropdown = toggleDropdown;
    window.handleDropdownKey = handleDropdownKey;
    window.showModal = showModal;
    window.closeModal = closeModal;
    window.closeDeleteModal = closeDeleteModal;
    window.fillFormWithData = fillFormWithData;
    window.disableFieldsInEdit = disableFieldsInEdit;
    window.disableAllFields = disableAllFields;
    window.handleSelectChange = handleSelectChange;
    window.saveEntity = saveEntity;
    window.deleteEntity = deleteEntity;
    window.toggleSelectAll = toggleSelectAll;
    window.handleBulkAction = handleBulkAction;
    window.uploadCsv = uploadCsv;
    window.getCookie = getCookie; // legacy fallback

    /* ── Bridge to ModalManager for focus-trap integration ─ */
    function notifyModalManager(action, modalId) {
        if (window.modalManager && typeof window.modalManager[action] === 'function') {
            try {
                window.modalManager[action](modalId);
            } catch (_) { /* ModalManager may not be loaded */ }
        }
    }

    // Wrap showModal/closeModal to notify ModalManager
    var _origShowModal = window.showModal;
    window.showModal = function(action, id) {
        _origShowModal(action, id);
        // Determine which modal is now visible
        var mainModal = document.getElementById(entityNameLower + 'Modal');
        var deleteModal = document.getElementById('deleteModal');
        if (action === 'delete' && deleteModal) {
            notifyModalManager('show', 'deleteModal');
        } else if (mainModal) {
            notifyModalManager('show', entityNameLower + 'Modal');
        }
    };

    var _origCloseModal = window.closeModal;
    window.closeModal = function() {
        _origCloseModal();
        notifyModalManager('hide', entityNameLower + 'Modal');
    };

    var _origCloseDelete = window.closeDeleteModal;
    window.closeDeleteModal = function() {
        _origCloseDelete();
        notifyModalManager('hide', 'deleteModal');
    };

    /* ------------------------------------------------------------------ */
    /*  Event binding on DOM ready                                          */
    /* ------------------------------------------------------------------ */
    document.addEventListener('DOMContentLoaded', function () {
        // Click-outside for dropdowns
        window.addEventListener('click', windowOnClick);
        // Click-outside for modals
        window.addEventListener('click', handleModalOutsideClick);
        // Register modals with ModalManager if available
        notifyModalManager('registerModal', entityNameLower + 'Modal');
        notifyModalManager('registerModal', 'deleteModal');
    });
})();
