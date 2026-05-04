/*
 * Modal Management - TecnoAgro
 * Gestión de modales, diálogos y overlays
 */

class ModalManager {
  constructor() {
    this.modals = new Map();
    this.currentModal = null;
    this.previousFocus = null;
    
    this.init();
  }

  init() {
    this.registerModals();
    this.bindGlobalEvents();
    this.setupEscClose();
    this.setupOutsideClickClose();
  }

  registerModals() {
    // Registrar modales existentes en el DOM que están marcados para gestión
    document.querySelectorAll('.modal-container[data-modal-managed="true"]').forEach(modal => {
      this.registerModal(modal.id);
    });
    
    // Registrar botones de apertura
    document.querySelectorAll('[data-modal-toggle]').forEach(button => {
      const modalId = button.getAttribute('data-modal-toggle');
      button.addEventListener('click', () => this.toggle(modalId));
    });
    
    document.querySelectorAll('[data-modal-show]').forEach(button => {
      const modalId = button.getAttribute('data-modal-show');
      button.addEventListener('click', () => this.show(modalId));
    });
  }

  // Registrar un modal manualmente por su ID
  registerModal(modalId) {
    const modal = document.getElementById(modalId);
    if (!modal) {
      console.warn(`Modal no encontrado: ${modalId}`);
      return;
    }
    
    if (this.modals.has(modalId)) {
      return; // ya registrado
    }
    
    this.modals.set(modalId, modal);
    
    // Configurar botones de cierre dentro del modal
    modal.querySelectorAll('[data-modal-hide]').forEach(button => {
      button.addEventListener('click', () => this.hide(modalId));
    });
    
    console.debug(`Modal registrado: ${modalId}`);
  }

  bindGlobalEvents() {
    // Evento personalizado para mostrar modales
    document.addEventListener('tecnoagro:showModal', (e) => {
      if (e.detail.modalId) {
        this.show(e.detail.modalId, e.detail.options);
      }
    });

    // Evento personalizado para ocultar modales
    document.addEventListener('tecnoagro:hideModal', (e) => {
      if (e.detail.modalId) {
        this.hide(e.detail.modalId);
      } else {
        this.hideAll();
      }
    });

    // Focus trap — ciclo Tab/Shift+Tab dentro del modal activo
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab' || !this.currentModal) return;
      const modal = this.modals.get(this.currentModal);
      if (!modal || modal.classList.contains('hidden')) return;

      const focusable = modal.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      const list = Array.from(focusable).filter(el => !el.disabled);
      if (list.length === 0) return;

      const first = list[0];
      const last = list[list.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    });
  }

  setupEscClose() {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && this.currentModal) {
        this.hide(this.currentModal);
      }
    });
  }

  setupOutsideClickClose() {
    document.addEventListener('click', (e) => {
      if (!this.currentModal) return;
      
      const modal = this.modals.get(this.currentModal);
      if (!modal) return;
      
      // Encontrar el backdrop (puede ser el mismo modal o un hijo con clase modal-backdrop)
      const backdrop = modal.querySelector('.modal-backdrop') || modal;
      
      // Si el clic fue en el backdrop (o en el modal mismo)
      if (backdrop.contains(e.target)) {
        // Verificar si el modal permite cerrar al hacer clic fuera
        if (!modal.hasAttribute('data-persistent')) {
          this.hide(this.currentModal);
        }
      }
    });
  }

  show(modalId, options = {}) {
    const modal = this.modals.get(modalId);
    if (!modal) {
      console.warn(`Modal no encontrado: ${modalId}`);
      return;
    }
    
    // Ocultar modal actual si existe
    if (this.currentModal && this.currentModal !== modalId) {
      this.hide(this.currentModal);
    }
    
    // Guardar elemento con foco actual
    this.previousFocus = document.activeElement;
    
    // Mostrar modal
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');
    
    // Bloquear scroll del body
    document.body.classList.add('overflow-hidden');
    
    // Aplicar opciones
    if (options.backdrop !== false) {
      modal.classList.add('modal-backdrop-visible');
    }
    
    // Configurar tamaño si se especifica
    if (options.size) {
      modal.classList.remove('modal-sm', 'modal-md', 'modal-lg', 'modal-xl');
      modal.classList.add(`modal-${options.size}`);
    }
    
    // Disparar evento personalizado
    modal.dispatchEvent(new CustomEvent('modal:show', { detail: options }));
    
    // Enfocar primer elemento enfocable
    this.focusFirstFocusable(modal);
    
    this.currentModal = modalId;
    
    // Disparar evento global
    document.dispatchEvent(new CustomEvent('tecnoagro:modalShown', {
      detail: { modalId, modal }
    }));
  }

  hide(modalId) {
    const modal = this.modals.get(modalId);
    if (!modal || modal.classList.contains('hidden')) return;
    
    // Disparar evento de ocultar
    modal.dispatchEvent(new CustomEvent('modal:hide'));
    
    // Ocultar modal
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
    
    // Restaurar scroll del body
    document.body.classList.remove('overflow-hidden');
    
    // Restaurar foco
    if (this.previousFocus && document.body.contains(this.previousFocus)) {
      this.previousFocus.focus();
    }
    
    this.currentModal = null;
    
    // Disparar evento global
    document.dispatchEvent(new CustomEvent('tecnoagro:modalHidden', {
      detail: { modalId }
    }));
  }

  toggle(modalId) {
    const modal = this.modals.get(modalId);
    if (!modal) return;
    
    if (modal.classList.contains('hidden')) {
      this.show(modalId);
    } else {
      this.hide(modalId);
    }
  }

  hideAll() {
    this.modals.forEach((modal, id) => {
      if (!modal.classList.contains('hidden')) {
        this.hide(id);
      }
    });
  }

  focusFirstFocusable(modal) {
    const focusableSelectors = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    const focusableElements = modal.querySelectorAll(focusableSelectors);
    
    if (focusableElements.length > 0) {
      // Buscar el primer elemento que no esté deshabilitado
      for (let element of focusableElements) {
        if (!element.disabled) {
          element.focus();
          break;
        }
      }
    }
  }

  // Métodos para crear modales dinámicamente
  create(options = {}) {
    const {
      id = `modal-${Date.now()}`,
      title = '',
      content = '',
      size = 'md',
      footer = null,
      closeButton = true,
      backdropClose = true,
      onShow = null,
      onHide = null
    } = options;
    
    // Crear elemento modal
    const modal = document.createElement('div');
    modal.id = id;
    modal.className = 'modal-container hidden fixed inset-0 z-50 overflow-y-auto';
    modal.setAttribute('aria-labelledby', `${id}-title`);
    modal.setAttribute('aria-hidden', 'true');
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('data-modal-managed', 'true');
    
    if (!backdropClose) {
      modal.setAttribute('data-persistent', 'true');
    }
    
    // Backdrop
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop fixed inset-0 bg-black/50 dark:bg-black/70';
    
    // Contenido del modal
    const modalContent = document.createElement('div');
    modalContent.className = `modal-content modal-${size} relative bg-white dark:bg-gray-800 rounded-xl shadow-xl mx-auto my-8 p-6`;
    
    // Header
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between mb-4';
    
    const titleElement = document.createElement('h3');
    titleElement.id = `${id}-title`;
    titleElement.className = 'text-lg font-semibold text-gray-900 dark:text-gray-100';
    titleElement.textContent = title;
    
    header.appendChild(titleElement);
    
    // Botón de cerrar
    if (closeButton) {
      const closeButtonElement = document.createElement('button');
      closeButtonElement.type = 'button';
      closeButtonElement.className = 'text-gray-400 hover:text-gray-500 dark:hover:text-gray-300';
      closeButtonElement.setAttribute('data-modal-hide', id);
      closeButtonElement.setAttribute('aria-label', 'Cerrar');
      
      closeButtonElement.innerHTML = `
        <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
        </svg>
      `;
      
      header.appendChild(closeButtonElement);
    }
    
    // Body
    const body = document.createElement('div');
    body.className = 'modal-body';
    
    if (typeof content === 'string') {
      body.innerHTML = content;
    } else if (content instanceof HTMLElement) {
      body.appendChild(content);
    } else {
      body.textContent = content;
    }
    
    // Footer
    let footerElement = null;
    if (footer) {
      footerElement = document.createElement('div');
      footerElement.className = 'modal-footer mt-6 flex justify-end space-x-3';
      
      if (typeof footer === 'string') {
        footerElement.innerHTML = footer;
      } else if (footer instanceof HTMLElement) {
        footerElement.appendChild(footer);
      } else {
        footerElement.textContent = footer;
      }
    }
    
    // Ensamblar modal
    modalContent.appendChild(header);
    modalContent.appendChild(body);
    if (footerElement) {
      modalContent.appendChild(footerElement);
    }
    
    modal.appendChild(backdrop);
    modal.appendChild(modalContent);
    
    // Añadir al DOM
    document.body.appendChild(modal);
    
    // Registrar modal
    this.modals.set(id, modal);
    
    // Configurar eventos
    if (onShow) {
      modal.addEventListener('modal:show', onShow);
    }
    
    if (onHide) {
      modal.addEventListener('modal:hide', onHide);
    }
    
    // Configurar botón de cerrar
    if (closeButton) {
      modal.querySelector(`[data-modal-hide="${id}"]`).addEventListener('click', () => this.hide(id));
    }
    
    return modal;
  }

  alert(options = {}) {
    const {
      title = 'Alerta',
      message = '',
      type = 'info',
      confirmText = 'Aceptar',
      onConfirm = null
    } = options;
    
    let icon = '';
    let iconColor = '';
    
    switch (type) {
      case 'success':
        icon = `
          <svg class="w-6 h-6 text-emerald-600 dark:text-emerald-400" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
          </svg>
        `;
        iconColor = 'text-emerald-600 dark:text-emerald-400';
        break;
      case 'error':
        icon = `
          <svg class="w-6 h-6 text-red-600 dark:text-red-400" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
          </svg>
        `;
        iconColor = 'text-red-600 dark:text-red-400';
        break;
      case 'warning':
        icon = `
          <svg class="w-6 h-6 text-amber-600 dark:text-amber-400" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
          </svg>
        `;
        iconColor = 'text-amber-600 dark:text-amber-400';
        break;
      default:
        icon = `
          <svg class="w-6 h-6 text-sky-600 dark:text-sky-400" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
          </svg>
        `;
        iconColor = 'text-sky-600 dark:text-sky-400';
    }
    
    const content = `
      <div class="flex">
        <div class="mr-4 flex-shrink-0">
          ${icon}
        </div>
        <div>
          <h4 class="text-lg font-medium text-gray-900 dark:text-gray-100 mb-2">${title}</h4>
          <p class="text-gray-600 dark:text-gray-400">${message}</p>
        </div>
      </div>
    `;
    
    const footer = `
      <button type="button" 
              class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition-colors"
              data-modal-hide>
        ${confirmText}
      </button>
    `;
    
    const modal = this.create({
      id: `alert-${Date.now()}`,
      title: '',
      content,
      size: 'md',
      footer,
      closeButton: false,
      backdropClose: false
    });
    
    // Configurar evento de confirmación
    const confirmButton = modal.querySelector('[data-modal-hide]');
    confirmButton.addEventListener('click', () => {
      if (onConfirm) onConfirm();
    });
    
    // Mostrar modal
    this.show(modal.id);
    
    return modal;
  }

  confirm(options = {}) {
    const {
      title = 'Confirmar',
      message = '¿Estás seguro?',
      confirmText = 'Confirmar',
      cancelText = 'Cancelar',
      onConfirm = null,
      onCancel = null
    } = options;
    
    return new Promise((resolve) => {
      const content = `
        <div class="flex">
          <div class="mr-4 flex-shrink-0">
            <svg class="w-6 h-6 text-amber-600 dark:text-amber-400" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
          </div>
          <div>
            <h4 class="text-lg font-medium text-gray-900 dark:text-gray-100 mb-2">${title}</h4>
            <p class="text-gray-600 dark:text-gray-400">${message}</p>
          </div>
        </div>
      `;
      
      const footer = `
        <div class="flex space-x-3">
          <button type="button" 
                  class="px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg transition-colors"
                  data-modal-hide>
            ${cancelText}
          </button>
          <button type="button" 
                  class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg transition-colors"
                  data-confirm-button>
            ${confirmText}
          </button>
        </div>
      `;
      
      const modal = this.create({
        id: `confirm-${Date.now()}`,
        title: '',
        content,
        size: 'md',
        footer,
        closeButton: false,
        backdropClose: false
      });
      
      // Configurar botones
      const cancelButton = modal.querySelector('[data-modal-hide]');
      const confirmButton = modal.querySelector('[data-confirm-button]');
      
      cancelButton.addEventListener('click', () => {
        if (onCancel) onCancel();
        resolve(false);
      });
      
      confirmButton.addEventListener('click', () => {
        if (onConfirm) onConfirm();
        resolve(true);
        this.hide(modal.id);
      });
      
      // Mostrar modal
      this.show(modal.id);
    });
  }
}

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
  window.modalManager = new ModalManager();
});

// Exportar para uso global
window.ModalManager = ModalManager;