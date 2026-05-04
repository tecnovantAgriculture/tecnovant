/*
 * Form Validation & UI - TecnoAgro
 * Maneja validación visual, estados y UI de formularios
 */

class FormManager {
  constructor() {
    this.forms = document.querySelectorAll('form[data-tecnoagro-form]');
    this.fileUploads = document.querySelectorAll('.file-upload');
    this.selects = document.querySelectorAll('select[data-enhanced]');
    
    this.init();
  }

  init() {
    this.setupFormValidation();
    this.setupFileUploads();
    this.setupEnhancedSelects();
    this.setupSteppers();
    this.setupInputMasks();
  }

  // Validación de formularios
  setupFormValidation() {
    this.forms.forEach(form => {
      const inputs = form.querySelectorAll('input, select, textarea');
      const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
      
      // Marcar campos como tocados al salir
      inputs.forEach(input => {
        input.addEventListener('blur', () => {
          input.dataset.touched = 'true';
          this.validateField(input);
        });
        
        // Validación en tiempo real para algunos campos
        if (input.type !== 'checkbox' && input.type !== 'radio') {
          input.addEventListener('input', () => {
            if (input.dataset.touched === 'true') {
              this.validateField(input);
            }
          });
        }
      });
      
      // Validación al enviar
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        
        let isValid = true;
        inputs.forEach(input => {
          input.dataset.touched = 'true';
          if (!this.validateField(input)) {
            isValid = false;
          }
        });
        
        if (isValid) {
          this.showFormSuccess(form);
          
          // Simular envío
          if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = `
              <svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
              Enviando...
            `;
            
            setTimeout(() => {
              form.reset();
              inputs.forEach(input => delete input.dataset.touched);
              
              if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = 'Enviar';
              }
              
              // Mostrar mensaje de éxito persistente
              this.showToast('Formulario enviado correctamente', 'success');
            }, 1500);
          }
        } else {
          this.showFormError(form, 'Por favor, corrige los errores señalados.');
          this.scrollToFirstError(form);
        }
      });
    });
  }

  validateField(field) {
    // Limpiar estados previos
    field.classList.remove('border-red-500', 'border-emerald-500');
    
    // Eliminar mensajes de error previos
    const errorMsg = field.parentElement?.querySelector('.field-error');
    if (errorMsg) errorMsg.remove();
    
    // Validar
    const isValid = field.checkValidity();
    
    if (!isValid) {
      field.classList.add('border-red-500');
      this.showFieldError(field);
      return false;
    } else if (field.value.trim() !== '') {
      field.classList.add('border-emerald-500');
    }
    
    return true;
  }

  showFieldError(field) {
    const container = field.parentElement;
    if (!container) return;
    
    const errorMsg = document.createElement('p');
    errorMsg.className = 'field-error text-xs text-red-600 dark:text-red-400 mt-1';
    
    if (field.validity.valueMissing) {
      errorMsg.textContent = field.dataset.requiredMessage || 'Este campo es obligatorio.';
    } else if (field.validity.typeMismatch) {
      if (field.type === 'email') {
        errorMsg.textContent = 'Por favor, introduce un correo electrónico válido.';
      } else {
        errorMsg.textContent = 'Formato inválido.';
      }
    } else if (field.validity.tooShort) {
      errorMsg.textContent = `Mínimo ${field.minLength} caracteres.`;
    } else if (field.validity.tooLong) {
      errorMsg.textContent = `Máximo ${field.maxLength} caracteres.`;
    } else if (field.validity.rangeUnderflow) {
      errorMsg.textContent = `El valor mínimo es ${field.min}.`;
    } else if (field.validity.rangeOverflow) {
      errorMsg.textContent = `El valor máximo es ${field.max}.`;
    } else if (field.validity.patternMismatch) {
      errorMsg.textContent = field.dataset.patternMessage || 'El formato no es válido.';
    } else {
      errorMsg.textContent = 'Valor inválido.';
    }
    
    container.appendChild(errorMsg);
  }

  showFormSuccess(form) {
    const successMsg = document.createElement('div');
    successMsg.className = 'mb-6 p-4 rounded-lg bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800';
    successMsg.innerHTML = `
      <div class="flex items-center">
        <svg class="w-5 h-5 text-emerald-600 dark:text-emerald-400 mr-3" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
        </svg>
        <div>
          <p class="font-medium text-emerald-800 dark:text-emerald-300">Formulario validado correctamente</p>
          <p class="text-sm text-emerald-700 dark:text-emerald-400 mt-1">Los datos han sido validados y están listos para enviar.</p>
        </div>
      </div>
    `;
    
    form.prepend(successMsg);
  }

  showFormError(form, message) {
    const errorMsg = document.createElement('div');
    errorMsg.className = 'mb-6 p-4 rounded-lg bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800';
    errorMsg.innerHTML = `
      <div class="flex items-center">
        <svg class="w-5 h-5 text-red-600 dark:text-red-400 mr-3" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
        </svg>
        <div>
          <p class="font-medium text-red-800 dark:text-red-300">Error en el formulario</p>
          <p class="text-sm text-red-700 dark:text-red-400 mt-1">${message}</p>
        </div>
      </div>
    `;
    
    form.prepend(errorMsg);
    
    // Auto-remove after 5 seconds
    setTimeout(() => errorMsg.remove(), 5000);
  }

  scrollToFirstError(form) {
    const firstError = form.querySelector('.border-red-500');
    if (firstError) {
      firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
      firstError.focus();
    }
  }

  // Upload de archivos
  setupFileUploads() {
    this.fileUploads.forEach(uploadArea => {
      const input = uploadArea.querySelector('input[type="file"]');
      const label = uploadArea.querySelector('.file-upload-label');
      const preview = uploadArea.querySelector('.file-preview');
      const clearBtn = uploadArea.querySelector('.file-clear');
      
      if (!input) return;
      
      // Drag & drop
      uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('border-emerald-500', 'bg-emerald-50/50');
      });
      
      uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('border-emerald-500', 'bg-emerald-50/50');
      });
      
      uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('border-emerald-500', 'bg-emerald-50/50');
        
        if (e.dataTransfer.files.length) {
          input.files = e.dataTransfer.files;
          this.updateFilePreview(input, label, preview, clearBtn);
        }
      });
      
      // Cambio manual
      input.addEventListener('change', () => {
        this.updateFilePreview(input, label, preview, clearBtn);
      });
      
      // Limpiar archivo
      if (clearBtn) {
        clearBtn.addEventListener('click', () => {
          input.value = '';
          if (label) label.textContent = label.dataset.defaultText || 'Arrastra archivos aquí o haz clic para seleccionar';
          if (preview) preview.classList.add('hidden');
          clearBtn.classList.add('hidden');
          uploadArea.classList.remove('border-emerald-500');
        });
      }
    });
  }

  updateFilePreview(input, label, preview, clearBtn) {
    if (!input.files.length) return;
    
    const file = input.files[0];
    const fileSize = (file.size / (1024 * 1024)).toFixed(2); // MB
    
    if (label) {
      label.innerHTML = `
        <span class="font-medium">${file.name}</span>
        <span class="text-xs text-gray-500 ml-2">(${fileSize} MB)</span>
      `;
    }
    
    if (preview) {
      if (file.type.startsWith('image/')) {
        const reader = new FileReader();
        reader.onload = (e) => {
          preview.innerHTML = `
            <img src="${e.target.result}" alt="Vista previa" class="max-h-32 mx-auto rounded">
          `;
          preview.classList.remove('hidden');
        };
        reader.readAsDataURL(file);
      } else {
        preview.innerHTML = `
          <div class="flex items-center justify-center p-4 bg-gray-100 dark:bg-gray-800 rounded">
            <svg class="w-12 h-12 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd"/>
            </svg>
          </div>
        `;
        preview.classList.remove('hidden');
      }
    }
    
    if (clearBtn) {
      clearBtn.classList.remove('hidden');
    }
  }

  // Selects mejorados
  setupEnhancedSelects() {
    this.selects.forEach(select => {
      const container = document.createElement('div');
      container.className = 'relative';
      
      const display = document.createElement('button');
      display.type = 'button';
      display.className = 'w-full px-4 py-2.5 text-left bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 flex items-center justify-between';
      display.innerHTML = `
        <span class="selected-value">${select.options[select.selectedIndex]?.text || 'Selecciona una opción'}</span>
        <svg class="w-5 h-5 text-gray-400" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
        </svg>
      `;
      
      const dropdown = document.createElement('div');
      dropdown.className = 'absolute z-50 w-full mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg hidden';
      
      // Crear opciones
      Array.from(select.options).forEach(option => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'w-full px-4 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700';
        item.textContent = option.text;
        item.dataset.value = option.value;
        
        if (option.selected) {
          item.classList.add('bg-emerald-50', 'dark:bg-emerald-900/30', 'text-emerald-700', 'dark:text-emerald-300');
        }
        
        item.addEventListener('click', () => {
          select.value = option.value;
          display.querySelector('.selected-value').textContent = option.text;
          
          // Actualizar estilos
          dropdown.querySelectorAll('button').forEach(btn => {
            btn.classList.remove('bg-emerald-50', 'dark:bg-emerald-900/30', 'text-emerald-700', 'dark:text-emerald-300');
          });
          item.classList.add('bg-emerald-50', 'dark:bg-emerald-900/30', 'text-emerald-700', 'dark:text-emerald-300');
          
          dropdown.classList.add('hidden');
          select.dispatchEvent(new Event('change'));
        });
        
        dropdown.appendChild(item);
      });
      
      // Toggle dropdown
      display.addEventListener('click', () => {
        dropdown.classList.toggle('hidden');
      });
      
      // Cerrar al hacer clic fuera
      document.addEventListener('click', (e) => {
        if (!container.contains(e.target)) {
          dropdown.classList.add('hidden');
        }
      });
      
      // Reemplazar select
      select.classList.add('hidden');
      container.appendChild(display);
      container.appendChild(dropdown);
      select.parentNode.insertBefore(container, select);
    });
  }

  // Steppers
  setupSteppers() {
    document.querySelectorAll('.stepper').forEach(stepper => {
      const steps = stepper.querySelectorAll('.stepper-step');
      const prevBtn = stepper.querySelector('[data-stepper-prev]');
      const nextBtn = stepper.querySelector('[data-stepper-next]');
      const forms = stepper.querySelectorAll('.stepper-form');
      
      let currentStep = 0;
      
      if (prevBtn) {
        prevBtn.addEventListener('click', () => {
          if (currentStep > 0) {
            currentStep--;
            updateStepper();
          }
        });
      }
      
      if (nextBtn) {
        nextBtn.addEventListener('click', () => {
          // Validar formulario actual antes de avanzar
          const currentForm = forms[currentStep];
          if (currentForm && !this.validateForm(currentForm)) {
            this.showFormError(currentForm, 'Por favor, corrige los errores antes de continuar.');
            return;
          }
          
          if (currentStep < steps.length - 1) {
            currentStep++;
            updateStepper();
          }
        });
      }
      
      function updateStepper() {
        steps.forEach((step, index) => {
          step.classList.remove('stepper-step-active', 'stepper-step-completed', 'stepper-step-pending');
          
          if (index < currentStep) {
            step.classList.add('stepper-step-completed');
          } else if (index === currentStep) {
            step.classList.add('stepper-step-active');
          } else {
            step.classList.add('stepper-step-pending');
          }
        });
        
        forms.forEach((form, index) => {
          form.classList.toggle('hidden', index !== currentStep);
        });
        
        // Actualizar botones
        if (prevBtn) {
          prevBtn.disabled = currentStep === 0;
        }
        
        if (nextBtn) {
          if (currentStep === steps.length - 1) {
            nextBtn.textContent = 'Finalizar';
            nextBtn.classList.add('bg-emerald-600', 'hover:bg-emerald-700');
          } else {
            nextBtn.textContent = 'Siguiente';
            nextBtn.classList.remove('bg-emerald-600', 'hover:bg-emerald-700');
          }
        }
      }
      
      updateStepper();
    });
  }

  // Máscaras de entrada
  setupInputMasks() {
    document.querySelectorAll('input[data-mask="phone"]').forEach(input => {
      input.addEventListener('input', (e) => {
        let value = e.target.value.replace(/\D/g, '');
        
        if (value.length > 10) {
          value = value.substring(0, 10);
        }
        
        if (value.length > 6) {
          value = `(${value.substring(0, 3)}) ${value.substring(3, 6)}-${value.substring(6)}`;
        } else if (value.length > 3) {
          value = `(${value.substring(0, 3)}) ${value.substring(3)}`;
        } else if (value.length > 0) {
          value = `(${value}`;
        }
        
        e.target.value = value;
      });
    });
    
    document.querySelectorAll('input[data-mask="number"]').forEach(input => {
      input.addEventListener('input', (e) => {
        let value = e.target.value.replace(/[^\d.]/g, '');
        
        // Permitir solo un punto decimal
        const parts = value.split('.');
        if (parts.length > 2) {
          value = parts[0] + '.' + parts.slice(1).join('');
        }
        
        e.target.value = value;
      });
    });
  }

  // Utilidades
  validateForm(form) {
    let isValid = true;
    const inputs = form.querySelectorAll('input[required], select[required], textarea[required]');
    
    inputs.forEach(input => {
      input.dataset.touched = 'true';
      if (!this.validateField(input)) {
        isValid = false;
      }
    });
    
    return isValid;
  }

  showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 z-50 px-6 py-4 rounded-lg shadow-lg transform transition-transform duration-300 translate-y-full`;
    
    const colors = {
      success: 'bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300',
      error: 'bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-800 dark:text-red-300',
      info: 'bg-sky-50 dark:bg-sky-900/30 border border-sky-200 dark:border-sky-800 text-sky-800 dark:text-sky-300',
      warning: 'bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300'
    };
    
    toast.className += ` ${colors[type] || colors.info}`;
    
    toast.innerHTML = `
      <div class="flex items-center">
        ${type === 'success' ? `
          <svg class="w-5 h-5 mr-3" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/>
          </svg>
        ` : ''}
        ${type === 'error' ? `
          <svg class="w-5 h-5 mr-3" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
          </svg>
        ` : ''}
        <span>${message}</span>
      </div>
    `;
    
    document.body.appendChild(toast);
    
    // Animar entrada
    setTimeout(() => {
      toast.classList.remove('translate-y-full');
    }, 10);
    
    // Auto-remove
    setTimeout(() => {
      toast.classList.add('translate-y-full');
      setTimeout(() => toast.remove(), 300);
    }, 5000);
  }
}

// Inicializar
document.addEventListener('DOMContentLoaded', () => {
  window.formManager = new FormManager();
});

// Exportar
window.FormManager = FormManager;
