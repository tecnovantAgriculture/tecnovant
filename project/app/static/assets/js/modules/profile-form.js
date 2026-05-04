/**
 * profile-form.js — User profile data update functionality.
 *
 * Depends on window.showAlert() for notifications.
 */
(function () {
    'use strict';

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
     * Initialize profile update form.
     */
    function initProfileForm() {
        var form = document.getElementById('profileForm');
        if (!form) return;

        form.addEventListener('submit', function (e) {
            e.preventDefault();

            var button = document.getElementById('updateProfileBtn');
            if (!button) return;

            var originalText = button.textContent;
            button.disabled = true;
            button.textContent = 'Actualizando...';

            var formData = {
                full_name: document.getElementById('full_name').value,
                email: document.getElementById('email').value,
                birthday: document.getElementById('birthday').value || null
            };

            fetch('/api/v1/core/profile', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRF-TOKEN': getCsrf()
                },
                body: JSON.stringify(formData)
            })
                .then(function (response) { return response.json().then(function (result) { return { response: response, result: result }; }); })
                .then(function (data) {
                    var response = data.response;
                    var result = data.result;
                    if (response.ok) {
                        window.showAlert('profile-alerts', result.msg || 'Perfil actualizado con éxito.', 'success');
                        // Update displayed name if changed
                        var h1 = document.querySelector('h1');
                        if (h1) h1.textContent = formData.full_name;
                    } else {
                        window.showAlert('profile-alerts', result.msg || result.error || 'Error al actualizar el perfil.', 'error');
                    }
                })
                .catch(function (error) {
                    console.error('Profile update error:', error);
                    window.showAlert('profile-alerts', 'Error de red o del servidor.', 'error');
                })
                .finally(function () {
                    button.disabled = false;
                    button.textContent = originalText;
                });
        });
    }

    /**
     * Initialize profile form on DOM ready.
     */
    window.ProfileForm = {
        init: function () {
            initProfileForm();
        }
    };

})();
