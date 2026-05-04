/*
 * Sidebar Navigation - TecnoAgro
 * Gestiona la navegación responsive y estados del sidebar
 */

class SidebarManager {
  constructor() {
    this.sidebar = document.getElementById('sidebar');
    this.toggleBtn = document.getElementById('sidebar-toggle');
    this.sidebarLinks = document.querySelectorAll('#sidebar a');
    this.submenuButtons = document.querySelectorAll('#sidebar [data-visible="onClick"] > button');
    this.currentPath = window.location.pathname;
    
    this.init();
  }

  init() {
    this.setupMobileBehavior();
    this.setupSubmenus();
    this.setupActiveLinks();
    this.setupDarkModeToggle();
    this.setupDesktopToggle();
    this.setupResizeListener();
  }

  // Comportamiento en móvil
  setupMobileBehavior() {
    if (!this.toggleBtn) return;

    // Toggle sidebar en móvil
    this.toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.sidebar.classList.toggle('mobile-drawer-open');
      document.body.classList.toggle('overflow-hidden');
      
      // Cerrar submenús al abrir/cerrar sidebar en móvil
      if (window.innerWidth < 768) {
        this.closeAllSubmenus();
      }
    });

    // Cerrar sidebar al hacer clic fuera (solo móvil)
    document.addEventListener('click', (e) => {
      if (window.innerWidth >= 768) return;
      
      if (this.sidebar.classList.contains('mobile-drawer-open') &&
          !this.sidebar.contains(e.target) &&
          !this.toggleBtn.contains(e.target)) {
        this.sidebar.classList.remove('mobile-drawer-open');
        document.body.classList.remove('overflow-hidden');
      }
    });

    // Cerrar sidebar al hacer clic en un enlace (móvil)
    this.sidebarLinks.forEach(link => {
      link.addEventListener('click', () => {
        if (window.innerWidth < 768) {
          this.sidebar.classList.remove('mobile-drawer-open');
          document.body.classList.remove('overflow-hidden');
        }
      });
    });
  }

  // Submenús expandibles
  setupSubmenus() {
    this.submenuButtons.forEach(button => {
      // Expandir/collapsar submenú
      button.addEventListener('click', (e) => {
        e.stopPropagation();
        
        // Si sidebar está colapsado, no hacer nada (los submenús están ocultos)
        if (document.documentElement.classList.contains('sidebar-collapsed')) {
          return;
        }
        
        // En móvil, solo toggle
        if (window.innerWidth < 768) {
          this.toggleSubmenu(button);
          return;
        }
        
        // En desktop, mantener abierto
        const isCurrentlyOpen = !button.nextElementSibling.classList.contains('hidden');
        
        // Cerrar otros submenús
        if (!isCurrentlyOpen) {
          this.closeOtherSubmenus(button);
        }
        
        this.toggleSubmenu(button);
      });

      // Keyboard support
      button.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          button.click();
        } else if (e.key === 'Escape') {
          this.closeSubmenu(button);
        }
      });
    });

    // Cerrar submenús al hacer clic fuera (solo desktop)
    document.addEventListener('click', (e) => {
      if (window.innerWidth < 768) return;
      
      if (!e.target.closest('[data-visible="onClick"]')) {
        this.closeAllSubmenus();
      }
    });
  }

  toggleSubmenu(button) {
    const submenu = button.nextElementSibling;
    if (!submenu) return;

    const isHidden = submenu.classList.contains('hidden');
    
    // Rotar ícono
    const icon = button.querySelector('svg:last-child');
    if (icon) {
      icon.classList.toggle('rotate-180', isHidden);
    }

    // Toggle visibilidad
    submenu.classList.toggle('hidden');
    
    // Actualizar aria-expanded
    button.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
  }

  closeSubmenu(button) {
    const submenu = button.nextElementSibling;
    if (!submenu || submenu.classList.contains('hidden')) return;

    const icon = button.querySelector('svg:last-child');
    if (icon) {
      icon.classList.remove('rotate-180');
    }

    submenu.classList.add('hidden');
    button.setAttribute('aria-expanded', 'false');
  }

  closeOtherSubmenus(currentButton) {
    this.submenuButtons.forEach(button => {
      if (button !== currentButton) {
        this.closeSubmenu(button);
      }
    });
  }

  closeAllSubmenus() {
    this.submenuButtons.forEach(button => this.closeSubmenu(button));
  }

  // Enlaces activos
  setupActiveLinks() {
    this.sidebarLinks.forEach(link => {
      const href = link.getAttribute('href');
      
      // Simple path matching (para prototipo)
      if (href && this.currentPath.includes(href.replace('.html', ''))) {
        link.classList.add('active');
        
        // Expandir parent submenu si existe
        const parentLi = link.closest('[data-visible="onClick"]');
        if (parentLi) {
          const button = parentLi.querySelector('button');
          if (button) {
            // Mark button as having an active child link
            button.setAttribute('data-submenu-active', 'true');
            this.openSubmenu(button);
          }
        }
      }
      
      // Añadir indicador visual
      if (link.classList.contains('active')) {
        const indicator = document.createElement('span');
        indicator.className = 'absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-emerald-500 rounded-r';
        link.style.position = 'relative';
        link.appendChild(indicator);
      }
    });
  }

  openSubmenu(button) {
    // Don't open submenus when sidebar is collapsed (they are hidden)
    if (document.documentElement.classList.contains('sidebar-collapsed')) {
      return;
    }
    
    const submenu = button.nextElementSibling;
    if (!submenu) return;

    const icon = button.querySelector('svg:last-child');
    if (icon) {
      icon.classList.add('rotate-180');
    }

    submenu.classList.remove('hidden');
    button.setAttribute('aria-expanded', 'true');
  }

  // Reopen active submenus when sidebar expands (after being collapsed)
  refreshActiveSubmenus() {
    // Find all buttons marked as having active child links
    const activeButtons = document.querySelectorAll('#sidebar [data-submenu-active="true"]');
    activeButtons.forEach(button => this.openSubmenu(button));
  }

  // Dark mode toggle en sidebar
  setupDarkModeToggle() {
    const darkModeToggle = document.getElementById('darkmode-toggle-sidebar');
    if (darkModeToggle) {
      darkModeToggle.addEventListener('click', () => {
        if (window.TecnoAgro) {
          window.TecnoAgro.toggleDarkMode();
        }
        
        // Actualizar ícono
        const sunIcon = darkModeToggle.querySelector('.sun-icon');
        const moonIcon = darkModeToggle.querySelector('.moon-icon');
        
        if (document.documentElement.classList.contains('dark')) {
          sunIcon?.classList.add('hidden');
          moonIcon?.classList.remove('hidden');
        } else {
          sunIcon?.classList.remove('hidden');
          moonIcon?.classList.add('hidden');
        }
      });
    }
  }

  // Desktop sidebar toggle functionality
  setupDesktopToggle() {
    const toggleBtn = document.getElementById('sidebar-toggle-desktop');
    if (!toggleBtn) return;

    // Set initial ARIA state based on current collapsed state
    const isCollapsed = document.documentElement.classList.contains('sidebar-collapsed');
    this.updateToggleAria(toggleBtn, isCollapsed);

    // Toggle on click
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isCurrentlyCollapsed = document.documentElement.classList.contains('sidebar-collapsed');
      
      // Toggle collapsed state
      if (isCurrentlyCollapsed) {
        document.documentElement.classList.remove('sidebar-collapsed');
        this.updateToggleAria(toggleBtn, false);
        this.saveSidebarState('expanded');
        // Reopen active submenus that were hidden during collapsed state
        this.refreshActiveSubmenus();
      } else {
        document.documentElement.classList.add('sidebar-collapsed');
        this.updateToggleAria(toggleBtn, true);
        this.saveSidebarState('collapsed');
        // Close all submenus when collapsing
        this.closeAllSubmenus();
      }
    });
  }

  updateToggleAria(toggleBtn, isCollapsed) {
    toggleBtn.setAttribute('aria-expanded', !isCollapsed);
    toggleBtn.setAttribute('aria-label', isCollapsed ? 'Expandir menú' : 'Colapsar menú');
  }

  saveSidebarState(state) {
    try {
      localStorage.setItem('sidebar_state', state);
    } catch (e) {
      console.warn('Failed to save sidebar state to localStorage:', e);
    }
  }

  // Listener para resize
  setupResizeListener() {
    let resizeTimeout;
    
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        // Cerrar sidebar en móvil al cambiar a desktop
        if (window.innerWidth >= 768) {
          this.sidebar.classList.remove('mobile-drawer-open');
          document.body.classList.remove('overflow-hidden');
        } else {
          // En móvil, cerrar todos los submenús
          this.closeAllSubmenus();
        }
      }, 250);
    });
  }

  // Métodos públicos
  open() {
    this.sidebar.classList.add('mobile-drawer-open');
    document.body.classList.add('overflow-hidden');
  }

  close() {
    this.sidebar.classList.remove('mobile-drawer-open');
    document.body.classList.remove('overflow-hidden');
  }

  toggle() {
    if (this.sidebar.classList.contains('mobile-drawer-open')) {
      this.close();
    } else {
      this.open();
    }
  }
}

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
  window.sidebarManager = new SidebarManager();
});

// Exportar para uso global
window.SidebarManager = SidebarManager;
