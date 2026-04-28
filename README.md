# Rclone Service Tray

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Qt](https://img.shields.io/badge/Qt-PySide6-41CD52?logo=qt&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-systemd_user-FCC624?logo=linux&logoColor=black)
![Desktop](https://img.shields.io/badge/Desktop-KDE%20Wayland-1D99F3?logo=kde&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

**Rclone Service Tray** es una aplicación de escritorio para Linux que vive en la bandeja del sistema y permite monitorear, reiniciar, detener, revisar logs y limpiar cache de montajes `rclone` gestionados con servicios `systemd --user`.

Está pensada para usuarios que montan varios remotos con archivos `.service`, por ejemplo:

```text
~/.config/systemd/user/rclone-Google-Drive.service
~/.config/systemd/user/rclone-OneDrive-Personal.service
~/.config/systemd/user/rclone-Dropbox.service
```

## Vista General

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                           Rclone Service Tray                              │
├────────────────────┬────────────┬───────────────┬───────────────────────────┤
│ Remoto             │ Estado     │ Actividad     │ Cache / Errores / Acciones│
├────────────────────┼────────────┼───────────────┼───────────────────────────┤
│ Google Drive       │ 🟢 Activo  │ ☁️ Inactivo   │ 2.4 GB · 0 errores        │
│ OneDrive Personal  │ 🟢 Activo  │ ⬇️ Descargando│ 850 MB · 0 errores        │
│ Dropbox            │ ⚠️ Error   │ ⚠️ Error      │ 120 MB · 1 error          │
│ Mega               │ 🔴 Parado  │ —             │ —                         │
└────────────────────┴────────────┴───────────────┴───────────────────────────┘
```

Desde el tray puedes:

- Abrir u ocultar la ventana principal.
- Reiniciar todos los montajes.
- Ver errores recientes.
- Limpiar todos los caches.
- Abrir ajustes.
- Salir de la aplicación.

## Qué Hace

Rclone Service Tray detecta servicios `rclone-*.service`, extrae información útil del `ExecStart` y ofrece un panel simple para administrarlos.

| Área | Función |
| --- | --- |
| Servicios | Detecta archivos `.service`, muestra estado y permite iniciar, detener o reiniciar. |
| Logs | Lee `journalctl --user` y archivos definidos con `--log-file`. |
| Errores | Detecta patrones como `ERROR`, `failed`, `permission denied` o `transport endpoint is not connected`. |
| Cache VFS | Calcula tamaño, cantidad de archivos y fecha de modificación. |
| Mantenimiento | Limpia cache por remoto o todos los caches con confirmación. |
| Editor | Permite editar `.service`, crea backup y valida con `systemd-analyze --user verify`. |
| Ajustes | Guarda preferencias en `~/.config/rclone-service-tray/config.json`. |

## Requisitos

- Debian Trixie, Ubuntu reciente u otra distribución Linux con systemd.
- Python 3.10 o superior.
- PySide6 / Qt6.
- rclone.
- Montajes gestionados como servicios de usuario.

En Debian Trixie, dependencias recomendadas:

```bash
sudo apt update
sudo apt install python3 python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets rclone systemd
```

## Instalación Para Desarrollo

```bash
git clone https://github.com/TU_USUARIO/rclone-service-tray.git
cd rclone-service-tray

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Ejecutar:

```bash
rclone-service-tray
```

También puedes lanzarlo sin instalar el entrypoint:

```bash
python3 -m rclonetray
```

## Instalación Desde .deb

Construir el paquete:

```bash
scripts/build_deb.sh
```

Instalar:

```bash
sudo apt install ./dist/rclone-service-tray_1.0.0_all.deb
```

Ejecutar desde terminal:

```bash
rclone-service-tray
```

O desde el menú de aplicaciones como **Rclone Service Tray**.

## Uso Como AppImage

Construir:

```bash
scripts/build_appimage.sh
```

Si `appimagetool` está instalado, se generará:

```text
dist/Rclone-Service-Tray-1.0.0-x86_64.AppImage
```

Ejecutar:

```bash
chmod +x dist/Rclone-Service-Tray-1.0.0-x86_64.AppImage
./dist/Rclone-Service-Tray-1.0.0-x86_64.AppImage
```

Si `appimagetool` no está disponible, el script genera un `AppDir` empaquetado como `.tar.gz` para pruebas locales.

## Cómo Deben Verse Tus Servicios

Rclone Service Tray detecta automáticamente:

```text
~/.config/systemd/user/rclone-*.service
```

Ejemplo de servicio:

```ini
[Unit]
Description=Rclone mount Google Drive
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/rclone mount Google-Drive: /home/usuario/CloudDrives/Google-Drive \
  --vfs-cache-mode full \
  --vfs-cache-max-size 20G \
  --dir-cache-time 72h \
  --poll-interval 15s \
  --log-file /home/usuario/.cache/rclone/Google-Drive.log \
  --rc \
  --rc-addr 127.0.0.1:5572
ExecStop=/bin/fusermount3 -u /home/usuario/CloudDrives/Google-Drive
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

Activar:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rclone-Google-Drive.service
```

## Cache VFS

Ruta por defecto:

```text
~/.cache/rclone/vfs/
```

La limpieza de cache sigue este flujo:

```text
1. Detener servicio systemd user
2. Validar que la ruta esté dentro de ~/.cache/rclone/vfs
3. Eliminar cache del remoto
4. Iniciar de nuevo el servicio
5. Mostrar resultado
```

Rclone Service Tray no usa `sudo` y no borra rutas fuera de la carpeta de cache configurada.

## Configuración

Archivo principal:

```text
~/.config/rclone-service-tray/config.json
```

Ejemplo:

```json
{
  "theme": "system",
  "services": [],
  "confirm_cache_clean": true,
  "start_minimized": true,
  "minimize_to_tray": true,
  "show_notifications": true,
  "refresh_interval_seconds": 10,
  "cache_refresh_interval_seconds": 60,
  "systemd_user_dir": "/home/usuario/.config/systemd/user",
  "mounts_base_dir": "/home/usuario/CloudDrives",
  "rclone_cache_dir": "/home/usuario/.cache/rclone/vfs",
  "logs_dir": "/home/usuario/.cache/rclone"
}
```

Logs internos:

```text
~/.config/rclone-service-tray/rclone-service-tray.log
```

## Comandos Que Usa

Rclone Service Tray ejecuta comandos con `subprocess.run([...])`, sin construir comandos shell concatenando texto.

```bash
systemctl --user start SERVICE
systemctl --user stop SERVICE
systemctl --user restart SERVICE
systemctl --user daemon-reload
systemctl --user status SERVICE --no-pager -l
journalctl --user -u SERVICE -p warning -n 50 --no-pager
systemd-analyze --user verify PATH_SERVICE
```

## Estructura Del Proyecto

```text
rclone-service-tray/
├── rclonetray/              # Paquete Python interno de la aplicación
│   ├── app.py               # Arranque Qt
│   ├── tray.py              # QSystemTrayIcon
│   ├── main_window.py       # Panel principal
│   ├── settings_window.py   # Ajustes
│   ├── service_parser.py    # Parser de .service
│   ├── systemd_manager.py   # systemctl --user
│   ├── cache_manager.py     # Cache VFS
│   └── log_manager.py       # journalctl y logs rclone
├── packaging/               # .deb, .desktop y AppImage
├── scripts/                 # Scripts de build
├── tests/                   # Tests unitarios
├── README.md
├── CHANGELOG.md
└── pyproject.toml
```

## Construcción De Artefactos

Todo:

```bash
scripts/build_all.sh
```

Solo `.deb`:

```bash
scripts/build_deb.sh
```

Solo AppImage:

```bash
scripts/build_appimage.sh
```

## Releases En GitHub

El workflow `.github/workflows/release.yml` construye artefactos al publicar tags:

```bash
git tag v1.0.0
git push origin v1.0.0
```

La release sube los archivos generados en `dist/`.

## Seguridad

- No usa `sudo`.
- Opera con `systemd --user`.
- Confirma operaciones destructivas.
- Valida rutas antes de borrar cache.
- No ejecuta `systemctl --user stop 'rclone-*.service'`.
- Usa la lista de servicios detectados o configurados por la app.
- Crea backup antes de guardar cambios en archivos `.service`.

## Estado Actual

Este repositorio contiene el MVP funcional inicial. La actividad en tiempo real todavía se estima mediante logs; la integración con rclone RC/API queda preparada para una versión futura.

## Roadmap

- Integración completa con rclone RC/API.
- Velocidades de transferencia y progreso por archivo.
- Actividad en tiempo real.
- Overlays o integración con Dolphin.
- Editor avanzado de parámetros rclone.
- Perfiles por remoto.
- Diagnóstico automático de errores frecuentes.

## Licencia

MIT. Consulta [LICENSE](LICENSE).
