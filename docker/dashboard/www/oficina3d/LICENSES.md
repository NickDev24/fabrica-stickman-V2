# Oficina 3D — de dónde salió cada archivo y qué se puede hacer con él

Los modelos GLB de esta carpeta son de [dandacompany/deskrpg](https://github.com/dandacompany/deskrpg),
tag `2026.1007.1`. Los bajó `tools/bajar_oficina3d.sh` y no se modificaron: se usan tal cual,
adentro del CRM de Fénix, como pantalla interna de uso propio.

## Licencia

`LICENCIA-DESKRPG.txt` es la **Sustainable Use License** textual del repo, sin recortar.
Lo que importa de ahí:

> You may use or modify the software only for your own internal business purposes or for
> non-commercial or personal use. You may distribute the software or provide it to others
> only if you do so free of charge for non-commercial purposes. You may not alter, remove,
> or obscure any licensing, copyright, or other notices of the licensor in the software.

O sea: **usar estos modelos en una pantalla interna del CRM está permitido**. Lo que no:
revenderlos, meterlos en un producto que se cobra, o exponerlos a terceros fuera del CRM
(`mp4-render.site/crm` vive detrás de un gate con clave). Si algún día esta vista se muestra
a alguien de afuera o se cobra, se reemplaza el arte por primitivas propias.

Los personajes derivan de packs de **Quaternius** publicados bajo **CC0 1.0**
(dominio público): el detalle está en `CREDITOS-PERSONAJES.md`, copiado del repo de origen.

## three.js

`static/vendor/three/` es **three@0.180.0** sin parches (MIT, SPDX dentro de cada archivo,
avisos de copyright intactos). Se vendorizan solo 7 archivos: `three.module.min.js` +
`three.core.js` (este último lo importa el primero con ruta relativa hardcodeada) y los
addons `GLTFLoader`, `BufferGeometryUtils` (transitivo del loader), `SkeletonUtils`,
`CSS2DRenderer`, `RoundedBoxGeometry`.

## Manifiesto

| archivo | origen en deskrpg | peso |
| --- | --- | --- |
| `characters/office-seo.glb` | `public/assets/characters/office/office-seo.glb` | 363 KB |
| `characters/office-bomi.glb` | `public/assets/characters/office/office-bomi.glb` | 534 KB |
| `characters/office-tae.glb` | `public/assets/characters/office/office-tae.glb` | 375 KB |
| `furniture/pub-workstation-v1.glb` | `public/assets/shared/publishing/pub-workstation-v1.glb` | 243 KB |
| `furniture/pub-print-bench-v1.glb` | `public/assets/shared/publishing/pub-print-bench-v1.glb` | 142 KB |
| `furniture/conference-table-v1.glb` | `public/assets/shared/furniture/conference-table-v1.glb` | 62 KB |
| `furniture/mobile-board-v1.glb` | `public/assets/shared/furniture/mobile-board-v1.glb` | 77 KB |

Los tres personajes traen los clips `idle`, `sit` y `walk` (1,92 unidades de alto →
**1 unidad = 1 metro**), que es lo que usa `static/js/oficina3d.js` para sentar a cada agente
en su escritorio. Los muebles no traen animación.

Sha256 de todo: `tools/bajar_oficina3d.sh` (al final de su salida) y
`static/vendor/three/SHA256SUMS` / `static/oficina3d/SHA256SUMS`.

Para re-traer o cambiar un modelo: `bash tools/bajar_oficina3d.sh --forzar`.
