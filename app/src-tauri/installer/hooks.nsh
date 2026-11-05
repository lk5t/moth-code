; MOTH Code installer theme.
; Included by Tauri's NSIS template (bundle.windows.nsis.installerHooks) before any
; Modern UI page is declared, so these defines style the whole installer.

; Black-and-crimson welcome/finish pages and page headers.
!define MUI_BGCOLOR "080808"
!define MUI_TEXTCOLOR "F2F2F2"
; Themed checkboxes ignore custom text colours (NSIS bug #443); classic controls make the
; finish-page checkbox labels readable on the dark background.
!define MUI_FORCECLASSICCONTROLS

!define MUI_WELCOMEPAGE_TITLE "Welcome to MOTH Code"
!define MUI_WELCOMEPAGE_TEXT "MOTH Code is an independent AI coding agent powered by its own neural network, trained from scratch on your PC.$\r$\n$\r$\nThis will install MOTH Code for your user account. No administrator rights are needed, and nothing is uploaded anywhere.$\r$\n$\r$\nClick Next to continue."
!define MUI_FINISHPAGE_TITLE "MOTH Code is ready"
!define MUI_FINISHPAGE_TEXT "MOTH Code has been installed.$\r$\n$\r$\nStart by opening a project folder, then train your first MOTH model from the Training view."
!define MUI_ABORTWARNING
!define MUI_ABORTWARNING_TEXT "Stop installing MOTH Code?"
