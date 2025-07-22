// Dark darkModeToggle
const darkModeToggle = document.getElementById('darkModeToggle');
const html = document.documentElement;

// Cargar la preferencia de modo oscuro desde localStorage
const darkModePreference = localStorage.getItem('dark-mode');

if (darkModePreference === 'enabled') {
    html.classList.add('dark');
}

darkModeToggle.addEventListener('click', () => {
    html.classList.toggle('dark');

    // Guardar la preferencia del usuario en localStorage
    if (html.classList.contains('dark')) {
        localStorage.setItem('dark-mode', 'enabled');
    } else {
        localStorage.setItem('dark-mode', 'disabled');
    }
});


document.addEventListener("DOMContentLoaded", () => {
    const sidebar = document.getElementById("default-sidebar");
    const toggleButton = document.querySelector("[data-drawer-toggle]");

    if (toggleButton) {
        toggleButton.addEventListener("click", () => {
            if (sidebar) {
                sidebar.classList.toggle("-translate-x-full");
            }
        });
    }

    document.addEventListener("click", (event) => {
        if (sidebar && toggleButton && !sidebar.contains(event.target) && !toggleButton.contains(event.target) && !sidebar.classList.contains("-translate-x-full")) {
            sidebar.classList.add("-translate-x-full");
        }
    });
});

// menu 
document.addEventListener('DOMContentLoaded', function() {
    const mobileMenuButton = document.getElementById('mobile-menu-button');
    const closeMenuButton = document.getElementById('close-menu-button');
    const menu = document.getElementById('menu');
    const menuList = menu ? menu.querySelector('ul') : null;
    const menuItems = menu ? menu.querySelectorAll('a') : [];

    function toggleMenu() {
        if (menu) {
            menu.classList.toggle('hidden');
            document.body.classList.toggle('overflow-hidden');

            if (window.innerWidth < 768) {  // mobile view
                closeMenuButton.classList.toggle('hidden', menu.classList.contains('hidden'));
                menu.classList.toggle('fixed', !menu.classList.contains('hidden'));
                menu.classList.toggle('inset-0', !menu.classList.contains('hidden'));
                menu.classList.toggle('z-50', !menu.classList.contains('hidden'));
                menu.classList.toggle('bg-white', !menu.classList.contains('hidden'));
                menu.classList.toggle('dark:bg-gray-900', !menu.classList.contains('hidden'));
                menu.classList.toggle('bg-opacity-95', !menu.classList.contains('hidden'));
                menu.classList.toggle('dark:bg-opacity-95', !menu.classList.contains('hidden'));

                if (menuList) {
                    menuList.classList.toggle('flex', !menu.classList.contains('hidden'));
                    menuList.classList.toggle('flex-col', !menu.classList.contains('hidden'));
                    menuList.classList.toggle('items-center', !menu.classList.contains('hidden'));
                    menuList.classList.toggle('justify-center', !menu.classList.contains('hidden'));
                    menuList.classList.toggle('h-full', !menu.classList.contains('hidden'));
                    menuList.classList.toggle('space-y-8', !menu.classList.contains('hidden'));
                }

                menuItems.forEach(item => {
                    item.classList.toggle('text-2xl', !menu.classList.contains('hidden'));
                    item.classList.toggle('font-medium', !menu.classList.contains('hidden'));
                });
            }
        }
    }

    if (mobileMenuButton && closeMenuButton && menu) {
        mobileMenuButton.addEventListener('click', toggleMenu);
        closeMenuButton.addEventListener('click', toggleMenu);

        // Close menu when clicking on a link in mobile view
        menuItems.forEach(link => {
            link.addEventListener('click', () => {
                if (window.innerWidth < 768) {
                    toggleMenu();
                }
            });
        });
    }

    // Handle window resize
    window.addEventListener('resize', function() {
        if (window.innerWidth >= 768) { // 768px is the 'md' breakpoint in Tailwind by default
            if (menu) {
                menu.classList.remove('hidden', 'fixed', 'inset-0', 'z-50', 'bg-white', 'dark:bg-gray-900', 'bg-opacity-95', 'dark:bg-opacity-95');
                menu.classList.add('block');
                if (closeMenuButton) closeMenuButton.classList.add('hidden');
                if (menuList) {
                    menuList.classList.remove('flex', 'flex-col', 'items-center', 'justify-center', 'h-full', 'space-y-8');
                }
                menuItems.forEach(item => {
                    item.classList.remove('text-2xl', 'font-medium');
                });
                document.body.classList.remove('overflow-hidden');
            }
        } else if (!menu.classList.contains('hidden')) {
            toggleMenu();
        }
    });
});
document.addEventListener('DOMContentLoaded', function() {
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function() {
            if (sidebar) { 
                sidebar.classList.toggle('sidebar-hidden');
            }
        });
    }
    
    function handleResize() {
        if (sidebar) { 
            if (window.innerWidth >= 768) {
                sidebar.classList.remove('sidebar-hidden');
            } else {
                sidebar.classList.add('sidebar-hidden');
            }
        }
    }
    
    window.addEventListener('resize', handleResize);
    handleResize(); 
});