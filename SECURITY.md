# Security policy

If you find a vulnerability in this addon or in the PolyAssetVault sign-in/listing flow it uses, email **[contact@vassbrekke.no](mailto:contact@vassbrekke.no)** with:

- This repository name (`polyassetvault-blender-addon`)
- Blender version and addon version
- A description of the issue and how to reproduce it
- Impact, if you know it

Please **do not** open a public GitHub issue for security reports.

We do not currently run a paid bug bounty.

Publishing this source lets you inspect the addon. That is not a third-party security audit and not a promise of an SLA.

## What this addon handles

- A 30-day device token after browser sign-in. Treat it like a password for that Blender install. Do not paste it into issues or screenshots.
- Marketplace traffic to `https://polyassetvault.com` (or the API base you set). Checkout and card details stay on the website.
- Purchased files and listing exports on disk in the download / temp folders you choose.

Reports that include a live device token, session cookie, or customer file should say so in the email so we can treat the message as sensitive.
