# Sentinel: Rayo's guard mode (plan, not built)

Status: **parked on 16 Nov 2026** at MG's request. Nothing is built or installed yet. MG approves before the build starts.

## What MG asked for

- A wrong password should take a photo of the person.
- A touch alone shouldn't open the laptop.
- Someone struggling to use the laptop should be photographed, because they should ask MG first.
- Rayo should know MG's face and the faces of people close to MG.
- Everything stays local; nothing goes to the cloud.

## Decisions so far

| Topic | Decision |
|---|---|
| Fingerprint | **Stays on** for unlock and `sudo` (MG's call). Only the enrolled finger (right index) opens it. |
| Camera | **Watch mode** while the screen is locked (MG chose this over "events only"). |
| Face recognition | In phase 1, because watch mode needs it so MG isn't photographed at every unlock. Local only. |
| Alerts | **Open.** Telegram (recommended), email, or laptop only. |
| Lockout | **Open.** Recommended: 5 wrong tries (passwords and fingers combined), then 10 minutes. |
| Known people at the laptop | **Open.** Recommended: log quietly, no alert. |

## Design

1. **Wrong password or wrong finger** at the login screen, the lock screen or `sudo`:
   - A photo each time.
   - An alert from the 2nd failure in a row.
   - A lockout after 5 (`pam_faillock`).
   - **How it's installed:** a `pam_exec` hook on the failure path, added through Ubuntu's `pam-auth-update` profile, not by editing `common-auth` by hand. It's marked `optional`, so it can never block a login.
   - **Own typos:** if a successful login follows within 2 minutes, the photos are marked "probably MG" and no alert goes out.
2. **Watch mode**: a user service that switches on when GNOME's screensaver reports the screen locked, and off at unlock. It runs in three tiers:
   1. a motion check at about 2 fps, low resolution
   2. face detection only when something moves
   3. recognition only when there's a face

   Outcomes:
   - MG: nothing happens.
   - A known person: logged.
   - A stranger: several photos, encrypted straight away, then an alert.
   - At unlock: if the face isn't MG's even though the fingerprint or password worked, alert.
   - It slows down on battery. The lid closed means the laptop sleeps and the camera is off.
3. **Face models**: OpenCV YuNet (detection) and SFace (recognition), both Apache-2.0, plus `python3-opencv` from Ubuntu.
   - Rayo stores **faceprints**, not photos.
   - Enrolment is "Rayo, learn my face" (about 20 frames, several angles) and "Rayo, this is Ade", only with that person's agreement. NDPA 2023 treats biometrics as sensitive data.
   - **A face never unlocks the laptop.** This is an RGB camera, so a photo of MG can fool it.
4. **Camera path**: the Dell IPU6 sensor (ov01a10) is read through libcamera (`libcamerasrc`, SoftISP RGB output). `/dev/video*` raw nodes don't give usable frames.
5. **Storage**:
   - A root-only evidence folder, plus `~/Documents/Rayo/Sentinel` (700), encrypted at rest.
   - Kept 30 days.
   - The face module never touches the network, and the cloud brains never receive images or faceprints. A test enforces this.
6. **Telling MG**:
   - A login-screen banner: "This laptop belongs to MG. Ask permission before using it."
   - The phone alert, if chosen.
   - At unlock Rayo says what happened, and the HUD's THREAT shows INTRUDER until it's been seen.
   - Optional guest account for people MG allows.
7. **Installation**: MG runs `sudo ./security/sentinel-install.sh`. Claude doesn't change login security. Test a wrong `sudo` password in a second terminal before closing anything. There's a one-line uninstaller.
8. **Done when**:
   - A test photo works.
   - Wrong password and wrong finger each produce a photo.
   - Watch mode recognises MG and flags a stranger.
   - CPU while locked has been measured and tuned.
   - The uninstall has been tested.

## Prior art checked on GitHub (12 Nov 2026)

| Project | Notes | What we take from it |
|---|---|---|
| boltgolt/howdy | MIT, 7.9k★. Issue #796: hangs on the XPS 9320 because it can't start the IPU6 camera | Skip |
| phucvinh57/biopass | MIT, 1.5.1. IPU6 / libcamera SoftISP fixed in #169 (31 Oct) | Reference for reading the camera; only relevant if face *login* is ever wanted |
| Just-Utkarsh/Intruder | **No licence** (read only, don't copy) | The watch-while-locked design, encrypted evidence, multi-pose enrolment, motion gate |
| marekdedic/login-webcam | GPL, 2016 | The PAM failure hook idea. Its sed installer and `/dev/video0` capture don't work on this laptop |
