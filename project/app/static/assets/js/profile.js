/**
 * profile.js — Orchestrator for profile page functionality.
 *
 * Initializes global helpers and delegaes to modular components:
 * - /js/modules/avatar-manager.js
 * - /js/modules/profile-form.js
 * - /js/modules/password-form.js
 *
 * Requires window.PROFILE_CONFIG to be set by the including template with:
 *   - avatarDefault        (string)  URL/path to default avatar
 *   - changePasswordUrl    (string)  URL for the change-password endpoint
 *
 * Usage in template:
 *   <script>window.PROFILE_CONFIG = { ... }; </script>
 *   <script src="/js/modules/avatar-manager.js"></script>
 *   <script src="/js/modules/profile-form.js"></script>
 *   <script src="/js/modules/password-form.js"></script>
 *   <script src="/js/profile.js"></script>
 */
(function () {
    'use strict';

    /* ------------------------------------------------------------------ */
    /*  Global Helpers                                                     */
    /* ------------------------------------------------------------------ */

    /**
     * Get CSRF token — prefers global getCsrfToken(), falls back to getCookie().
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
     * Legacy getCookie fallback.
     */
    function getCookie(name) {
        var cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            var cookies = document.cookie.split(';');
            for (var i = 0; i < cookies.length; i++) {
                var cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    /**
     * Display an alert message in the specified container.
     */
    function showAlert(containerId, message, type) {
        if (type === undefined) type = 'success';
        var alertContainer = document.getElementById(containerId);
        if (!alertContainer) return;

        var alertTypeClass = type === 'success'
            ? 'bg-emerald-100 border-emerald-400 text-emerald-700'
            : 'bg-red-100 border-red-400 text-red-700';

        var alertHTML = '<div class="' + alertTypeClass + ' border px-4 py-3 rounded relative mb-4" role="alert">' +
            '<span class="block sm:inline">' + message + '</span>' +
            '<button type="button" class="absolute top-0 bottom-0 right-0 px-4 py-3" onclick="this.parentElement.remove();">' +
            '<svg class="fill-current h-6 w-6 ' + (type === 'success' ? 'text-emerald-500' : 'text-red-500') + '" role="button" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><title>Close</title><path d="M14.348 14.849a1 1 0 0 1-1.697 0L10 11.819l-2.651 3.029a1 2 0 1 1-1.697-1.697l2.758-3.15-2.759-3.152a1.2 1.2 0 1 1 1.697-1.697L10 8.183l2.651-3.031a1.2 1.2 0 1 1 1.697 1.697l-2.758 3.152 2.758 3.15a1.2 1.2 0 0 1 0 1.698z"/></svg>' +
            '</button></div>';

        alertContainer.innerHTML = alertHTML;
    }

    /* ------------------------------------------------------------------ */
    /*  Global Exposure & Init                                             */
    /* ------------------------------------------------------------------ */

    window.showAlert = showAlert;
    window.getCookie = getCookie; // legacy fallback

    document.addEventListener('DOMContentLoaded', function () {
        // Initialize modular components if available
        if (window.AvatarManager) {
            window.AvatarManager.init();
        }
        if (window.ProfileForm) {
            window.ProfileForm.init();
        }
        if (window.PasswordForm) {
            window.PasswordForm.init();
        }
    });

})();
