# WebODM en Google Cloud para TecnoAgro

Esta guia deja WebODM trabajando en una maquina de Google Cloud, mientras TecnoAgro sigue siendo la plataforma que recibe fotos, envia el procesamiento y descarga la ortofoto.

## Objetivo

- TecnoAgro puede correr local o en servidor pequeno.
- WebODM corre en una VM grande de Google Cloud.
- La VM se prende solo cuando se va a procesar.
- Al terminar, se apaga para no pagar CPU/RAM.

## Configuracion recomendada inicial

Para probar con ortofotos de unas 200 fotos:

```text
Nombre: webodm-tecnoagro
Sistema: Ubuntu 22.04 LTS o Ubuntu 24.04 LTS
CPU/RAM prueba: 24 vCPU / 96 GB RAM
CPU/RAM ideal: 32 vCPU / 128 GB RAM
Disco: 1 TB SSD / Balanced Persistent Disk / Hyperdisk Balanced
Puerto WebODM: 8000
```

Si Google no deja crear 24 o 32 vCPU por cuota inicial, crear primero:

```text
16 vCPU / 64 GB RAM
500 GB SSD
```

## Crear la VM

1. Entrar a Google Cloud Console.
2. Seleccionar el proyecto `tecnoagro-ortofotos`.
3. Ir a `Compute Engine > Instancias de VM`.
4. Crear instancia.
5. Usar Ubuntu LTS.
6. Elegir CPU/RAM.
7. Configurar disco de 500 GB o 1 TB.
8. Permitir IP externa.
9. Crear la instancia.

## Abrir puerto 8000

Crear una regla de firewall:

```text
Nombre: allow-webodm-8000
Target tag: webodm
Source IPv4 ranges: 0.0.0.0/0
Protocol/port: tcp:8000
```

Agregar el network tag `webodm` a la VM.

Para produccion, cambiar `0.0.0.0/0` por la IP del servidor donde corre TecnoAgro.

## Instalar WebODM en la VM

Entrar por SSH a la VM y ejecutar:

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y git curl ca-certificates
```

Instalar Docker:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

```bash
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Instalar WebODM:

```bash
git clone https://github.com/WebODM/WebODM --config core.autocrlf=input --depth 1
cd WebODM
sudo ./webodm.sh start
```

Abrir:

```text
http://IP_PUBLICA_DE_GOOGLE:8000
```

Crear el usuario de WebODM:

```text
Usuario: Tecnovan
Password: uno nuevo y seguro
```

## Conectar TecnoAgro con WebODM cloud

En `project/.env`, cambiar:

```env
WEBODM_URL=http://host.docker.internal:8000
```

por:

```env
WEBODM_URL=http://IP_PUBLICA_DE_GOOGLE:8000
WEBODM_PUBLIC_URL=http://IP_PUBLICA_DE_GOOGLE:8000
WEBODM_USERNAME=Tecnovan
WEBODM_PASSWORD=PASSWORD_WEBODM_CLOUD
WEBODM_PROJECT_NAME=Tecnovan
WEBODM_REQUEST_TIMEOUT_SECONDS=60
WEBODM_UPLOAD_TIMEOUT_SECONDS=7200
WEBODM_PROCESSING_PROFILE=fast_2d
```

Luego reiniciar TecnoAgro:

```powershell
cd C:\Users\juans\App_Tecnovan\tecnoagro
docker compose restart web
```

## Probar

1. Entrar a TecnoAgro.
2. Ir a `Ortofotos`.
3. Elegir una mision real.
4. Presionar `Procesar 2D rapido`.
5. Verificar en WebODM cloud que la tarea aparezca.
6. Esperar resultado y descargar TIFF/ZIP desde TecnoAgro.

## Apagar la VM

Despues de probar, apagar la VM desde:

```text
Compute Engine > Instancias de VM > webodm-tecnoagro > Detener
```

Cuando la VM esta detenida, no se paga CPU/RAM, pero el disco sigue generando costo.

## Siguiente fase

Despues de validar tiempos y calidad, TecnoAgro debe automatizar:

```text
1. Prender VM de Google
2. Esperar WebODM
3. Enviar fotos
4. Monitorear tarea
5. Descargar resultado
6. Apagar VM
```

