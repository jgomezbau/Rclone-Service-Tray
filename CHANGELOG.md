# Changelog

Todos los cambios importantes de Rclone Service Tray se documentarán en este archivo.

El formato está inspirado en [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) y el proyecto sigue versionado semántico cuando aplique.

## [1.0.0] - 2026-04-28

### Added

- MVP inicial de Rclone Service Tray con Python 3 y PySide6.
- Icono en system tray mediante `QSystemTrayIcon`.
- Ventana principal con tabla de remotos, estado, actividad, punto de montaje, cache, errores y acciones.
- Detección automática de servicios `rclone-*.service` en `~/.config/systemd/user/`.
- Carga manual de archivos `.service`.
- Parser de `ExecStart` para detectar remoto, punto de montaje, logs y flags de rclone.
- Acciones de servicio usando `systemctl --user`: iniciar, detener, reiniciar, estado y `daemon-reload`.
- Validación de archivos `.service` con `systemd-analyze --user verify`.
- Editor interno de `.service` con backup automático antes de guardar.
- Lectura de errores recientes desde `journalctl --user` y archivos `--log-file`.
- Detección básica de actividad por patrones en logs.
- Gestión de cache VFS por remoto.
- Limpieza segura de cache por remoto y limpieza global con confirmación.
- Ajustes persistidos en `~/.config/rclone-service-tray/config.json`.
- Temas `system`, `light` y `dark`.
- Notificaciones de escritorio mediante el tray.
- Empaquetado `.deb`.
- Script de construcción AppImage/AppDir.
- Workflow de GitHub Releases para tags `v*`.
- Tests iniciales para parser de servicios y seguridad de rutas de cache.

### Security

- No se usa `sudo`.
- No se construyen comandos shell con texto concatenado.
- Se valida que las rutas de cache estén dentro de la carpeta configurada antes de borrar.
- No se usan patrones globales para detener servicios; se opera sobre la lista de servicios cargados.

### Known Limitations

- La actividad en tiempo real se estima desde logs.
- La integración rclone RC/API queda para versiones futuras.
- El AppImage puede requerir ajustes adicionales para distribución pública amplia.
