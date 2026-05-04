/**
 * main.js — Global utilities
 *
 * Responsibilities:
 *  - Dark-mode toggle (persisted in localStorage)
 *  - Top navigation mobile menu (hamburger)
 *
 * Sidebar logic (mobile drawer, desktop collapse, submenus, active links)
 * lives exclusively in sidebar.js to avoid duplication.
 */

/* ── Dark Mode ─────────────────────────────────────────────────── */
(function initDarkMode() {
    const html = document.documentElement;
    const toggleBtn = document.getElementById('darkModeToggle');

    // Restore saved preference
    const saved = localStorage.getItem('dark-mode');
    if (saved === 'enabled') {
        html.classList.add('dark');
    }

    if (!toggleBtn) return;

    toggleBtn.addEventListener('click', function () {
        html.classList.toggle('dark');
        localStorage.setItem(
            'dark-mode',
            html.classList.contains('dark') ? 'enabled' : 'disabled'
        );
    });
})();

/* ── Top Navigation — Mobile Menu ──────────────────────────────── */
(function initMobileMenu() {
    const openBtn = document.getElementById('mobile-menu-button');
    const closeBtn = document.getElementById('close-menu-button');
    const menu = document.getElementById('menu');
    const menuList = menu ? menu.querySelector('ul') : null;
    const menuItems = menu ? menu.querySelectorAll('a') : [];

    if (!openBtn || !closeBtn || !menu) return;

    function toggleMenu() {
        const isOpen = !menu.classList.contains('hidden');
        const isMobile = window.innerWidth < 768;

        menu.classList.toggle('hidden');
        document.body.classList.toggle('overflow-hidden', !isOpen);

        if (isMobile) {
            closeBtn.classList.toggle('hidden', isOpen);

            if (!isOpen) {
                menu.classList.add('fixed', 'inset-0', 'z-50',
                    'bg-white', 'dark:bg-gray-900',
                    'bg-opacity-95', 'dark:bg-opacity-95');
                menuList?.classList.add('flex', 'flex-col',
                    'items-center', 'justify-center', 'h-full', 'space-y-8');
                menuItems.forEach(item =>
                    item.classList.add('text-2xl', 'font-medium'));
            } else {
                menu.classList.remove('fixed', 'inset-0', 'z-50',
                    'bg-white', 'dark:bg-gray-900',
                    'bg-opacity-95', 'dark:bg-opacity-95');
                menuList?.classList.remove('flex', 'flex-col',
                    'items-center', 'justify-center', 'h-full', 'space-y-8');
                menuItems.forEach(item =>
                    item.classList.remove('text-2xl', 'font-medium'));
            }
        }
    }

    openBtn.addEventListener('click', toggleMenu);
    closeBtn.addEventListener('click', toggleMenu);

    // Close on link click (mobile)
    menuItems.forEach(link => {
        link.addEventListener('click', function () {
            if (window.innerWidth < 768 && !menu.classList.contains('hidden')) {
                toggleMenu();
            }
        });
    });

    // Reset on resize past mobile breakpoint
    window.addEventListener('resize', function () {
        if (window.innerWidth >= 768 && !menu.classList.contains('hidden')) {
            menu.classList.remove('hidden', 'fixed', 'inset-0', 'z-50',
                'bg-white', 'dark:bg-gray-900',
                'bg-opacity-95', 'dark:bg-opacity-95');
            menu.classList.add('block');
            closeBtn.classList.add('hidden');
            menuList?.classList.remove('flex', 'flex-col',
                'items-center', 'justify-center', 'h-full', 'space-y-8');
            menuItems.forEach(item =>
                item.classList.remove('text-2xl', 'font-medium'));
            document.body.classList.remove('overflow-hidden');
        }
    });
})();
