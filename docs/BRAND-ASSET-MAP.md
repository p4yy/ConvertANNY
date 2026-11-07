# Approved brand integration

Source of truth: `branding/source/ConvertANNY_Approved_Logo_Reference.png` from the user-provided bundle. The wheel is an interaction control, not the application logo.

| Surface | Resource |
| --- | --- |
| Executable, taskbar, titlebar, tray | `src/assets/convertanny.ico` (approved supplied ICO) |
| Workspace, wheel centre, About | shared `runtime.app_icon()` |
| Desktop and Start | installed executable resource index 0 |
| Installer and uninstaller | compiled with approved ICO |
| Editable icon geometry | `src/assets/brand/ConvertANNY.svg` |
| Outlined wordmarks | `src/assets/brand/ConvertANNY-horizontal-*.svg` |
| Monochrome source variants | `src/assets/brand/glyph-*.svg` |
| Icon PNG exports | `src/assets/brand/icon-*.png` |
| Store/MSIX scale and target-size art | `packaging/StoreAssets/` |
| Bundled font | `src/assets/fonts/InterVariable.ttf`, license in `licenses/Inter-OFL.txt` |

The reference wordmark's exact original font has not been verified. The outlined wordmark reconstruction uses licensed Inter Bold and is a close reconstruction rather than an asserted exact font match. Actual runtime icon imagery remains the approved supplied derivative. MSIX identity is local preparation only; publisher identity and SDK validation are required before distribution.
