/**
 * avatar-manager.js — Avatar upload and removal functionality.
 *
 * Requires window.PROFILE_CONFIG with avatarDefault.
 * Depends on window.showAlert() for notifications.
 */
(function () {
    'use strict';

    var avatarDefault = (window.PROFILE_CONFIG || {}).avatarDefault || '';

    /**
     * Get CSRF token.
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
     * Initialize avatar change button and form visibility.
     */
    function initAvatarButtons() {
        var avatarUploadSection = document.getElementById('avatar-upload-section');
        var changeAvatarBtn = document.getElementById('change-avatar-btn');
        var cancelAvatarBtn = document.getElementById('cancel-avatar-btn');
        var avatarFileInput = document.getElementById('avatar-file');
        var avatarPreview = document.getElementById('avatar-preview');
        var avatarImage = document.getElementById('avatar-image');
        var removeAvatarBtn = document.getElementById('remove-avatar-btn');

        if (changeAvatarBtn) {
            changeAvatarBtn.addEventListener('click', function () {
                if (avatarUploadSection) avatarUploadSection.classList.remove('hidden');
            });
        }

        if (cancelAvatarBtn) {
            cancelAvatarBtn.addEventListener('click', function () {
                if (avatarUploadSection) avatarUploadSection.classList.add('hidden');
                if (avatarFileInput) avatarFileInput.value = '';
                if (avatarPreview && avatarImage) avatarPreview.src = avatarImage.src;
            });
        }

        if (avatarFileInput) {
            avatarFileInput.addEventListener('change', function (e) {
                var file = e.target.files[0];
                if (file && avatarPreview) {
                    var reader = new FileReader();
                    reader.onload = function (event) {
                        avatarPreview.src = event.target.result;
                    };
                    reader.readAsDataURL(file);
                }
            });
        }

        if (removeAvatarBtn) {
            removeAvatarBtn.addEventListener('click', function () {
                handleAvatarRemoval(removeAvatarBtn, avatarImage, avatarPreview);
            });
        }
    }

    /**
     * Handle avatar upload form submission.
     */
    function initAvatarForm() {
        var form = document.getElementById('avatarForm');
        if (!form) return;

        form.addEventListener('submit', function (e) {
            e.preventDefault();

            var button = document.getElementById('upload-avatar-btn');
            var avatarFileInput = document.getElementById('avatar-file');
            var avatarImage = document.getElementById('avatar-image');
            var avatarPreview = document.getElementById('avatar-preview');
            var avatarUploadSection = document.getElementById('avatar-upload-section');
            var removeAvatarBtn = document.getElementById('remove-avatar-btn');

            if (!button) return;

            var originalText = button.textContent;
            button.disabled = true;
            button.textContent = 'Subiendo...';

            var file = avatarFileInput ? avatarFileInput.files[0] : null;
            if (!file) {
                window.showAlert('avatar-alerts', 'Por favor selecciona una imagen.', 'error');
                button.disabled = false;
                button.textContent = originalText;
                return;
            }

            // Client-side file size validation (max 5 MB)
            var maxSize = 5 * 1024 * 1024;
            if (file.size > maxSize) {
                window.showAlert('avatar-alerts', 'El archivo es demasiado grande. Máximo 5 MB.', 'error');
                button.disabled = false;
                button.textContent = originalText;
                return;
            }

            var formData = new FormData();
            formData.append('file', file);

            fetch('/api/v1/core/profile/avatar', {
                method: 'POST',
                headers: {
                    'X-CSRF-TOKEN': getCsrf()
                },
                body: formData
            })
                .then(function (response) { return response.json().then(function (result) { return { response: response, result: result }; }); })
                .then(function (data) {
                    var response = data.response;
                    var result = data.result;
                    if (response.ok) {
                        window.showAlert('avatar-alerts', result.message || 'Avatar actualizado con éxito.', 'success');
                        if (result.avatar_url) {
                            if (avatarImage) avatarImage.src = result.avatar_url;
                            if (avatarPreview) avatarPreview.src = result.avatar_url;
                        }
                        if (avatarUploadSection) avatarUploadSection.classList.add('hidden');
                        if (avatarFileInput) avatarFileInput.value = '';
                        if (removeAvatarBtn) removeAvatarBtn.classList.remove('hidden');
                        setTimeout(function () { location.reload(); }, 1500);
                    } else {
                        window.showAlert('avatar-alerts', result.msg || result.error || 'Error al subir avatar.', 'error');
                    }
                })
                .catch(function (error) {
                    console.error('Avatar upload error:', error);
                    window.showAlert('avatar-alerts', 'Error de red o del servidor.', 'error');
                })
                .finally(function () {
                    button.disabled = false;
                    button.textContent = originalText;
                });
        });
    }

    /**
     * Handle avatar removal.
     */
    function handleAvatarRemoval(button, avatarImage, avatarPreview) {
        if (!confirm('¿Estás seguro de que deseas eliminar tu avatar?')) return;

        var originalText = button.textContent;
        button.disabled = true;
        button.textContent = 'Eliminando...';

        fetch('/api/v1/core/profile/avatar', {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRF-TOKEN': getCsrf()
            }
        })
            .then(function (response) { return response.json().then(function (result) { return { response: response, result: result }; }); })
            .then(function (data) {
                var response = data.response;
                var result = data.result;
                if (response.ok) {
                    window.showAlert('avatar-alerts', result.message || 'Avatar eliminado con éxito.', 'success');
                    if (avatarImage) avatarImage.src = avatarDefault;
                    if (avatarPreview) avatarPreview.src = avatarDefault;
                    button.classList.add('hidden');
                    setTimeout(function () { location.reload(); }, 1500);
                } else {
                    window.showAlert('avatar-alerts', result.msg || result.error || 'Error al eliminar avatar.', 'error');
                }
            })
            .catch(function (error) {
                console.error('Avatar removal error:', error);
                window.showAlert('avatar-alerts', 'Error de red o del servidor.', 'error');
            })
            .finally(function () {
                button.disabled = false;
                button.textContent = originalText;
            });
    }

    /**
     * Initialize avatar management on DOM ready.
     */
    window.AvatarManager = {
        init: function () {
            initAvatarButtons();
            initAvatarForm();
        }
    };

})();
