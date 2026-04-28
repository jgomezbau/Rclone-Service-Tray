# Rclone Service Tray

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Qt](https://img.shields.io/badge/Qt-PySide6-41CD52?logo=qt&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-systemd_user-FCC624?logo=linux&logoColor=black)
![Desktop](https://img.shields.io/badge/Desktop-KDE%20Wayland-1D99F3?logo=kde&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

**Rclone Service Tray** es una aplicacion de escritorio para Linux que vive en la bandeja del sistema y administra montajes `rclone` gestionados con servicios `systemd --user`.

La app detecta servicios `rclone-*.service`, interpreta su `ExecStart`, muestra estado, actividad, punto de montaje, espacio local usado, errores detectados por la app y un menu contextual por remoto.

> **Disclaimer:** este proyecto es independiente y no tiene relacion, afiliacion, patrocinio ni respaldo oficial de `rclone` o sus mantenedores. La app administra servicios y archivos locales de `rclone` en tu sesion de usuario. No usa `sudo` ni modifica datos del cloud, pero acciones como `Liberar espacio en disco`, `Limpiar logs` o editar un `.service` pueden afectar montajes activos, archivos locales cacheados y configuraciones de usuario. Revise las rutas configuradas y los backups antes de usarlo en entornos criticos.

Pensada para entornos como:

```text
~/.config/systemd/user/rclone-Google-Drive.service
~/.config/systemd/user/rclone-OneDrive-Personal.service
~/.config/systemd/user/rclone-Dropbox.service
~/.config/systemd/user/rclone-Nextcloud.service
```

## Vista general

| Remoto | Estado | Actividad | API | Punto de montaje | Espacio | Errores | Menu |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| Google-Drive | Activo | Inactivo | RC activo | `/home/usuario/CloudDrives/Google-Drive` | 2.4 GB | 0 | `⋮` |
| OneDrive-Personal | Activo | Subiendo | RC activo | `/home/usuario/CloudDrives/OneDrive-Personal` | 850 MB | 0 | `⋮` |
| Nextcloud | Con errores | Error reciente | No responde | `/home/usuario/CloudDrives/Nextcloud` | 120 MB | 1 | `⋮` |
| Dropbox | Detenido | Inactivo | No configurado | `/home/usuario/CloudDrives/Dropbox` | 0 B | 0 | `⋮` |

Desde el tray puedes:

- Abrir u ocultar la ventana principal.
- Reiniciar todos los servicios visibles.
- Ver errores recientes desde logs originales.
- Liberar espacio en disco para todos los remotos visibles.
- Abrir ajustes.
- Salir de la aplicacion.

## Funcionalidades actuales

### Servicios

- Deteccion automatica de `~/.config/systemd/user/rclone-*.service`.
- Soporte para servicios agregados manualmente desde Ajustes.
- Posibilidad de ignorar servicios sin borrarlos del sistema.
- Los servicios ignorados no aparecen en la pantalla principal ni participan en acciones globales.
- Estado consultado via `systemctl --user`.

### Parser de `ExecStart`

El parser soporta lineas multilinea con `\` y extrae correctamente:

- `remote`: primer argumento no-flag que termina en `:`
- `remote_name`: el mismo remoto sin `:`
- `mount_point`: argumento inmediatamente posterior al remoto
- `log_file`: valor de `--log-file`, tanto en `--log-file=/ruta` como `--log-file /ruta`

Ejemplo soportado:

```ini
ExecStart=/usr/bin/rclone mount \
  --config=/home/usuario/.config/rclone/rclone.conf \
  --vfs-cache-mode full \
  --vfs-cache-max-size 20G \
  --dir-cache-time 72h \
  --poll-interval 15s \
  --log-file /home/usuario/.cache/rclone/Google-Drive.log \
  --rc \
  --rc-addr 127.0.0.1:5572 \
  Google-Drive: /home/usuario/CloudDrives/Google-Drive
```

### Menus y acciones por remoto

La UI separa acciones de estado y acciones completas:

- Clic en la columna `Estado`:
  - Iniciar
  - Detener
  - Reiniciar
  - Ver estado systemd
- Boton `⋮` por fila:
  - Iniciar
  - Detener
  - Reiniciar
  - Ver estado
  - Abrir ubicacion
  - Ver actividad
  - Ver archivos locales
  - Ver logs
  - Ver errores
  - Editar `.service`
  - Validar `.service`
  - Liberar espacio en disco
  - Recargar daemon

Todos los menus usan iconos consistentes con `QIcon.fromTheme()` y fallback local.

### Actividad reciente

La actividad usa `rclone RC/API` como fuente principal cuando el servicio tiene `--rc` configurado y responde. Si RC no esta configurado, o no responde, la app mantiene la deteccion por logs como fallback.

Prioridad de fuente:

1. RC/API disponible
2. Logs recientes
3. Sin actividad

Cuando la fuente es logs:

- Se parsean timestamps con formato `YYYY/MM/DD HH:MM:SS`.
- La actividad solo cuenta si ocurrio dentro de `activity_window_seconds`.
- Una linea `vfs cache: cleaned ... to upload 0, uploading 0` fuerza estado inactivo.
- Estados detectados:
  - `idle`
  - `uploading`
  - `downloading`
  - `syncing`
  - `reading`
  - `writing`
  - `cleaning`
  - `error`

La columna `Actividad` se anima con un `QTimer` ligero:

- `Subiendo`: alternancia de flechas
- `Descargando`: alternancia de flechas
- `Sincronizando`: spinner simple
- `Liberando espacio`: spinner simple
- `Error reciente`: icono estatico
- `Inactivo`: nube estatica

### Actividad en tiempo real con rclone RC/API

RC/API es opcional. Si un servicio tiene `--rc`, Rclone Service Tray intenta consultar:

- `rc/noop`
- `core/version`
- `core/stats`

La app usa `core/stats` para obtener actividad actual:

- transferencias activas
- checks activos
- bytes transferidos
- total estimado
- velocidad
- archivos activos cuando rclone los expone

Ejemplo seguro por servicio:

```ini
ExecStart=/usr/bin/rclone mount \
  --vfs-cache-mode full \
  --log-file /home/usuario/.cache/rclone/Google-Drive.log \
  --rc \
  --rc-addr 127.0.0.1:5573 \
  --rc-no-auth \
  Google-Drive: /home/usuario/CloudDrives/Google-Drive
```

Use un puerto distinto por servicio:

| Remoto | Puerto sugerido |
| --- | ---: |
| Google Drive | 5573 |
| OneDrive Personal | 5574 |
| Dropbox | 5575 |
| Mega | 5576 |
| Nextcloud | 5577 |

Reglas de seguridad:

- Se recomienda siempre `127.0.0.1`.
- No se recomienda `0.0.0.0`.
- Si se detecta `0.0.0.0`, la UI muestra una advertencia porque RC podria quedar expuesto a la red.
- Si se usa `--rc-user` y `--rc-pass`, la app prepara Basic Auth y no muestra la contraseña en claro.
- Los logs siguen siendo la fuente para errores, diagnostico historico y auditoria.

En la pantalla principal, la columna `API` muestra:

- `RC activo`
- `No configurado`
- `No responde`
- `Inseguro`

En Ajustes -> Servicios -> Detalle se puede:

- ver si RC fue detectado
- ver direccion y URL
- probar conexion RC
- generar una sugerencia de configuracion RC con puerto recomendado

### Errores

La app separa claramente dos fuentes:

#### 1. Historial detectado por la app

- Archivo: `~/.config/rclone-service-tray/errors.jsonl`
- Es la fuente que alimenta:
  - contador de errores en la tabla principal
  - flag `recent_error`
  - actividad `⚠️ Error reciente`
- Se puede limpiar por servicio o globalmente.
- Si se limpia, no reaparece automaticamente salvo que se detecte un error nuevo posterior al momento de limpieza.

#### 2. Logs originales

- Fuente: `journalctl --user` y el `--log-file` configurado en cada remoto.
- Solo lectura desde la ventana `Ver errores`.
- Limpiar historial no modifica esta fuente.

### Ventana `Ver errores`

Cada remoto abre un dialogo con dos pestañas:

- `Historial detectado`
- `Logs originales`

Incluye:

- agrupacion de errores repetidos por mensaje normalizado
- cantidad
- primera vez
- ultima vez
- texto aclaratorio de que limpiar historial no toca logs originales

Si el historial esta vacio, se muestra:

```text
No hay errores registrados por la app para este servicio.
```

### Diagnostico inteligente para WebDAV / Nextcloud

Si un remoto parece `WebDAV` o `Nextcloud` y aparecen patrones como:

- `lookup`
- `127.0.0.53:53`
- `i/o timeout`
- `server misbehaving`
- `Propfind`

la ventana `Ver errores` muestra una sugerencia especifica:

```text
El error parece relacionado con resolucion DNS local o conectividad hacia el servidor
WebDAV/Nextcloud. Verifique resolvectl, conectividad con el dominio y disponibilidad del servidor.
```

Con comandos sugeridos:

```bash
resolvectl query DOMINIO
curl -I URL_BASE
rclone lsf REMOTO: --max-depth 1 -vv
```

### Deteccion de errores

Se consideran errores reales solo si aparecen patrones como:

- `ERROR`
- `CRITICAL`
- `Failed to`
- `failed to`
- `fatal`
- `panic`
- `permission denied`
- `transport endpoint is not connected`
- `rateLimitExceeded`
- `unauthenticated`
- `couldn't`
- `cannot`
- `corrupt`

No se cuentan como error lineas normales tipo:

- `INFO`
- `DEBUG`
- `NOTICE`
- `vfs cache: cleaned`
- `Committing uploads - please wait`
- `Copied (new)`
- `upload succeeded`
- `queuing for upload`
- `renamed in cache`
- `removed cache file`

### Logs

La app trabaja con logs en tres contextos:

- `Ver logs` por servicio
- `Ver errores` por servicio
- mantenimiento global desde Ajustes

En `Ver logs` por servicio se puede:

- Abrir archivo de log
- Abrir carpeta de logs
- Limpiar log de este servicio

La limpieza de logs originales:

- no usa `sudo`
- no usa `shell=True`
- no detiene el servicio
- no borra el archivo
- trunca el archivo de forma segura
- valida que el path exista y este dentro de una ruta segura

### Archivos locales y liberacion de espacio

La app llama `archivos locales` a los archivos del VFS local de rclone.

Desde `Ver archivos locales` puedes ver:

- Archivo
- Tamaño
- Ultima modificacion
- Ruta local
- Abrir archivo

Y tambien:

- Abrir ubicacion
- Liberar espacio en disco

La liberacion de espacio del VFS sigue este flujo:

```text
1. Detener temporalmente el servicio systemd --user
2. Validar que la ruta este dentro de ~/.cache/rclone/vfs
3. Eliminar los archivos locales del remoto
4. Iniciar de nuevo el servicio
5. Refrescar la UI y mostrar resultado
```

### Tray

El icono del tray mantiene el icono base de nube de la aplicacion y compone overlays dinamicos en la esquina superior derecha.

Prioridad global:

1. Error
2. Upload activo por RC
3. Download activo por RC
4. Sync activo por RC
5. Actividad estimada por logs
6. Idle

Estados visuales:

- error reciente: overlay de alerta con parpadeo suave
- subida: flecha hacia arriba animada
- descarga: flecha hacia abajo animada
- sincronizacion: spinner simple animado
- sin actividad: solo la nube base

Tooltip dinamico:

- `Rclone Service Tray\nTodos los servicios inactivos`
- `Rclone Service Tray\nActividad: subiendo archivos`
- `Rclone Service Tray\nErrores detectados en N servicios`

Se puede desactivar desde Ajustes con `show_tray_indicators`.

### Ajustes

La ventana de Ajustes se organiza en:

- `Servicios`
- `Apariencia`
- `Comportamiento`
- `Rutas`
- `Mantenimiento`

Funciones destacadas:

- Servicios detectados con checkbox `Activo en Rclone Service Tray`
- Detalle RC/API por servicio
- Prueba de conexion RC
- Sugerencia de configuracion RC con puerto recomendado
- Boton `Ignorar`
- Boton `Restaurar ignorados`
- Seleccion de carpetas para systemd, montajes, archivos locales y logs
- Tema `system`, `light` o `dark`
- Inicio minimizado
- Minimizar al cerrar
- Notificaciones
- Indicadores en el icono del tray
- Intervalo de refresco
- Ventana de actividad

### Mantenimiento general

Desde Ajustes -> `Mantenimiento`:

- Ver tamaño total ocupado por archivos locales
- Ver tamaño total de logs
- Liberar espacio en disco de todos los remotos visibles
- Limpiar logs de todos los servicios visibles
- Limpiar historial de errores general
- Reiniciar todos los servicios activos
- Recargar daemon systemd user

Todas las operaciones destructivas piden confirmacion.

## Requisitos

- Linux con `systemd --user`
- Python 3.10 o superior
- PySide6 / Qt6
- rclone
- Servicios `rclone-*.service`

En Debian Trixie o Ubuntu reciente:

```bash
sudo apt update
sudo apt install python3 rclone systemd
```

Si usas el Python del sistema, instala tambien PySide6 por tu metodo habitual. En entorno virtual:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

## Ejecucion

Con entrypoint instalado:

```bash
rclone-service-tray
```

Sin instalar el script:

```bash
python3 -m rclonetray
```

## Instalacion de paquetes

Construir `.deb`:

```bash
scripts/build_deb.sh
```

Instalar:

```bash
sudo apt install ./dist/rclone-service-tray_1.0.0_all.deb
```

Construir AppImage:

```bash
scripts/build_appimage.sh
```

Si `appimagetool` existe, el resultado esperado es:

```text
dist/Rclone-Service-Tray-1.0.0-x86_64.AppImage
```

## Ejemplo de servicio compatible

```ini
[Unit]
Description=Rclone mount Nextcloud
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/rclone mount \
  --config=/home/usuario/.config/rclone/rclone.conf \
  --vfs-cache-mode full \
  --vfs-cache-max-size 10G \
  --vfs-cache-max-age 168h \
  --dir-cache-time 168h \
  --poll-interval 15m \
  --log-file=/home/usuario/.local/state/rclone/rclone-nextcloud.log \
  --allow-other \
  Nextcloud: /home/usuario/CloudDrives/Nextcloud
ExecStop=/bin/fusermount3 -u /home/usuario/CloudDrives/Nextcloud
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

Activacion:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rclone-Nextcloud.service
```

## Configuracion

Archivo principal:

```text
~/.config/rclone-service-tray/config.json
```

Ejemplo completo:

```json
{
  "theme": "system",
  "services": [],
  "ignored_services": [],
  "last_error_clear_time": {},
  "confirm_cache_clean": true,
  "start_minimized": true,
  "minimize_to_tray": true,
  "show_notifications": true,
  "show_tray_indicators": true,
  "refresh_interval_seconds": 10,
  "cache_refresh_interval_seconds": 60,
  "activity_window_seconds": 60,
  "systemd_user_dir": "/home/usuario/.config/systemd/user",
  "mounts_base_dir": "/home/usuario/CloudDrives",
  "rclone_cache_dir": "/home/usuario/.cache/rclone/vfs",
  "logs_dir": "/home/usuario/.cache/rclone"
}
```

Otros archivos usados por la aplicacion:

```text
~/.config/rclone-service-tray/rclone-service-tray.log
~/.config/rclone-service-tray/errors.jsonl
```

## Comandos usados por la app

La app ejecuta comandos con `subprocess.run([...])`, sin `shell=True`.

```bash
systemctl --user start SERVICE
systemctl --user stop SERVICE
systemctl --user restart SERVICE
systemctl --user daemon-reload
systemctl --user status SERVICE --no-pager -l
journalctl --user -u SERVICE -p warning -n 50 --no-pager
systemd-analyze --user verify PATH_SERVICE
xdg-open MOUNTPOINT
xdg-open LOG_PATH
xdg-open LOGS_DIR
```

## Seguridad y limites

- No usa `sudo`.
- Opera solo con `systemd --user`.
- Confirma operaciones destructivas.
- Valida rutas antes de truncar logs o borrar archivos locales.
- No usa patrones destructivos sobre `rclone-*.service`.
- No toca archivos fuera de las rutas configuradas como seguras.
- Al guardar un `.service`, crea backup antes de escribir.

## Estructura del proyecto

```text
rclone-service-tray/
├── rclonetray/
│   ├── activity_detector.py
│   ├── app.py
│   ├── cache_manager.py
│   ├── config.py
│   ├── dialogs.py
│   ├── icons.py
│   ├── log_manager.py
│   ├── main.py
│   ├── main_window.py
│   ├── notifications.py
│   ├── service_model.py
│   ├── service_parser.py
│   ├── settings_window.py
│   ├── systemd_manager.py
│   ├── theme_manager.py
│   ├── tray.py
│   └── resources/icons/
├── packaging/
├── scripts/
├── tests/
├── README.md
├── CHANGELOG.md
└── pyproject.toml
```

## Tests

El proyecto incluye tests unitarios para:

- parser de `ExecStart`
- actividad reciente
- limpieza segura de logs
- agrupacion y diagnostico de errores
- filtrado de servicios ignorados
- reglas de cache

Suite:

```bash
pytest
```

## Roadmap

- Integracion completa con rclone RC/API
- Velocidades de transferencia y progreso por archivo
- Actividad en tiempo real
- Overlays o integracion con Dolphin
- Editor avanzado de parametros rclone
- Perfiles por remoto
- Diagnostico automatico de errores frecuentes
- Exportacion de eventos y errores

## Licencia

MIT. Consulta [LICENSE](LICENSE).
