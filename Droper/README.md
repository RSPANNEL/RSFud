# Update_dropper_MiHRK (Java)

A safe sample Android app (Java) with a message screen and a Proceed button that requests directory access using the Storage Access Framework. No APK installation is performed.

## Build
- Open this folder in Android Studio (Giraffe+).
- Let it sync Gradle. Use JDK 17.
- Run on a device or emulator (API 24+; target SDK 34).

## Flow
- App shows a message.
- Tap Proceed to pick a folder.
- On success, the app persists read/write access to that folder URI.
