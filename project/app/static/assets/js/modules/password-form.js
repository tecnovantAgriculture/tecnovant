/**
 * password-form.js — Password change functionality.
 *
 * Requires window.PROFILE_CONFIG with changePasswordUrl.
 * Depends on window.showAlert() for notifications.
 */
(function () {
    'use strict';

    var changePasswordUrl = (window.PROFILE_CONFIG || {}).changePasswordUrl || '';

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
     * Initialize password change form.
     */
    function initPasswordForm() {
        var form = document.getElementById('passwordForm');
        if (!form) return;

        form.addEventListener('submit', function (e) {
            e.preventDefault();

            var button = document.getElementById('updatePasswordBtn');
            if (!button) return;

            var originalText = button.textContent;
            button.disabled = true;
            button.textContent = 'Actualizando...';

            var formData = {
                current_password: document.getElementById('current_password').value,
                new_password: document.getElementById('new_password').value,
                confirm_password: document.getElementById('confirm_password').value
            };

            fetch(changePasswordUrl, {
                method: 'POST',
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
                        window.showAlert('password-alerts', result.msg || 'Contraseña actualizada con éxito.', 'success');
                        document.getElementById('passwordForm').reset();
                    } else {
                        window.showAlert('password-alerts', result.msg || result.error || 'Error al cambiar la contraseña.', 'error');
                    }
                })
                .catch(function (error) {
                    console.error('Password change error:', error);
                    window.showAlert('password-alerts', 'Error de red o del servidor.', 'error');
                })
                .finally(function () {
                    button.disabled = false;
                    button.textContent = originalText;
                });
        });
    }

    /**
     * Initialize password form on DOM ready.
     */
    window.PasswordForm = {
        init: function () {
            initPasswordForm();
        }
    };

})();
