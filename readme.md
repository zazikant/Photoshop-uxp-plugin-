1. Photoshop plugin requires UXP installer from Creative Cloud.
2. Create a new plugin mandatory from UXP installer. Give it a name "Gemini Images Generator" and ID as `gemini.image.generator`. It will create `gemini.image.generator` in UXP path having `External` folder. If `External` folder not found, create it in same level path having `Internal` folder.
3. The `External` folder has `manifest.json`, `main.js`, and `index.html`. `index.html` points to `main.js`.

Now very important: when you close Photoshop, UXP plugin also closes. So you need to click on "Load and Watch" when the script is first time created. It will have "Watching" state. So when you click on "Reload" your plugin will work. No need to close Photoshop.
