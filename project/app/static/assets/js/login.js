async function apiLogin(username, password) {
    const messageDiv = document.getElementById('message');

    try {
        const response = await fetch('/auth/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({
                username: username,
                password: password // Enviar la contraseña directamente
            })
        });

        const data = await response.json();

        if (response.ok) {
            messageDiv.style.color = 'green';
            messageDiv.textContent = data.msg;
            // Redirigir al usuario o actualizar la interfaz según sea necesario
        } else {
            messageDiv.style.color = 'red';
            messageDiv.textContent = data.msg;
        }
    } catch (error) {
        console.error('Error durante el inicio de sesión:', error);
        messageDiv.style.color = 'red';
        messageDiv.textContent = 'Ocurrió un error. Por favor, intenta de nuevo más tarde.';
    }
}

// Manejar el evento de envío del formulario
document.getElementById('loginForm').addEventListener('submit', async function(event) {
    event.preventDefault(); // Prevenir el comportamiento por defecto del formulario

    // Obtener los valores del formulario
    const username = document.getElementById('username').value.trim();
    const password = document.getElementById('password').value;

    // Validar campos (opcional)
    if (!username || !password) {
        const messageDiv = document.getElementById('message');
        messageDiv.style.color = 'red';
        messageDiv.textContent = 'Por favor, completa ambos campos.';
        return;
    }

    // Llamar a la función de inicio de sesión
    await apiLogin(username, password);
});