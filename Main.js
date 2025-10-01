
```javascript
/*
 * Photoshop + Gemini 2.5 Flash IMAGE GENERATION Script
 * Generate and edit images directly with Gemini (Nano Banana style)
 * 
 * Setup Instructions:
 * 1. Get your Gemini API key from https://aistudio.google.com/app/apikey
 * 2. Replace YOUR_API_KEY_HERE below with your actual key
 * 3. File → Scripts → Browse → Select this file
 * 4. A dialog will appear with all options
 * 
 * Quick Usage:
 * - Generate New: Creates image from text prompt
 * - Edit Selection: Press Q, paint area, press Q, then edit
 * - Quick Transforms: One-click blur, remove, enhance, etc.
 */

const { app } = require("photoshop");
const { batchPlay } = require("photoshop").action;
const fs = require("uxp").storage.localFileSystem;

// ===== CONFIGURATION =====
const GEMINI_API_KEY = "YOUR_API_KEY_HERE"; // Replace with your actual API key
const GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image-preview";
const GEMINI_VISION_MODEL = "gemini-2.0-flash-exp";

// ===== API ENDPOINTS =====
function getGenerateEndpoint() {
    return `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_IMAGE_MODEL}:generateContent?key=${GEMINI_API_KEY}`;
}

function getVisionEndpoint() {
    return `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_VISION_MODEL}:generateContent?key=${GEMINI_API_KEY}`;
}

// ===== UTILITY FUNCTIONS =====

function checkApiKey() {
    if (GEMINI_API_KEY === "YOUR_API_KEY_HERE" || !GEMINI_API_KEY) {
        alert("⚠️ API Key Required!\n\n" +
              "1. Get your key from:\n https://aistudio.google.com/app/apikey\n\n" +
              "2. Open this script file\n\n" +
              "3. Replace YOUR_API_KEY_HERE with your actual key\n\n" +
              "4. Save and run again");
        return false;
    }
    return true;
}

async function checkSelection() {
    try {
        const result = await batchPlay([
            {
                _obj: "get",
                _target: [
                    { _property: "selection" },
                    { _ref: "document", _enum: "ordinal", _value: "targetEnum" }
                ]
            }
        ], {});
        return result[0].selection !== undefined;
    } catch (e) {
        return false;
    }
}

async function getSelectionBounds() {
    try {
        const result = await batchPlay([
            {
                _obj: "get",
                _target: [
                    { _property: "selection" },
                    { _ref: "document", _enum: "ordinal", _value: "targetEnum" }
                ]
            }
        ], {});
        
        if (result[0].selection) {
            const bounds = result[0].selection;
            return {
                top: bounds.top._value,
                left: bounds.left._value,
                bottom: bounds.bottom._value,
                right: bounds.right._value,
                width: bounds.right._value - bounds.left._value,
                height: bounds.bottom._value - bounds.top._value
            };
        }
    } catch (e) {
        return null;
    }
}

async function createHistoryState(name) {
    try {
        await batchPlay([
            {
                _obj: "make",
                _target: [{ _ref: "snapshotClass" }],
                from: { _ref: "historyState", _property: "currentHistoryState" },
                name: name
            }
        ], {});
    } catch (e) {
        // History state creation failed, continue anyway
    }
}

// ===== CORE IMAGE FUNCTIONS =====

async function getSelectionAsBase64() {
    const doc = app.activeDocument;
    
    const hasSelection = await checkSelection();
    if (!hasSelection) {
        return null;
    }

    try {
        // Copy merged selection
        await batchPlay([{ _obj: "copyMerged" }], {});

        // Paste as new layer
        await batchPlay([{ _obj: "paste" }], {});

        const layer = doc.activeLayers[0];
        const tempFile = await fs.createTemporaryFile("selection.png");
        
        // Export to PNG
        const token = await fs.createSessionToken(tempFile);
        await layer.saveAs(tempFile, { 
            token,
            format: "png"
        });

        // Read as base64
        const fileEntry = await fs.getEntryWithUrl(tempFile.nativePath);
        const buffer = await fileEntry.read({ format: fs.formats.binary });
        const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));

        // Clean up temp layer
        await batchPlay([
            {
                _obj: "delete",
                _target: [{ _ref: "layer", _enum: "ordinal", _value: "targetEnum" }]
            }
        ], {});

        return base64;
    } catch (error) {
        console.error("Error getting selection:", error);
        throw error;
    }
}

async function getDocumentAsBase64() {
    const doc = app.activeDocument;
    const tempFile = await fs.createTemporaryFile("document.png");
    
    try {
        const token = await fs.createSessionToken(tempFile);
        await doc.saveAs(tempFile, { 
            token,
            format: "png"
        });

        const fileEntry = await fs.getEntryWithUrl(tempFile.nativePath);
        const buffer = await fileEntry.read({ format: fs.formats.binary });
        const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));

        return base64;
    } catch (error) {
        console.error("Error getting document:", error);
        throw error;
    }
}

async function createLayerFromBase64(base64Data, layerName = "Gemini Generated") {
    const doc = app.activeDocument;
    
    // Save base64 to temp file
    const tempFile = await fs.createTemporaryFile("generated.png");
    const fileEntry = await fs.getEntryWithUrl(tempFile.nativePath);
    
    // Convert base64 to binary
    const binaryString = atob(base64Data);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
    }
    
    await fileEntry.write(bytes, { format: fs.formats.binary });
    
    // Place the file as a new layer
    await batchPlay([
        {
            _obj: "placeEvent",
            null: {
                _path: tempFile.nativePath,
                _kind: "local"
            },
            freeTransformCenterState: { 
                _enum: "quadCenterState", 
                _value: "QCSAverage" 
            }
        }
    ], {});
    
    // Rename layer
    const layer = doc.activeLayers[0];
    layer.name = layerName;
    
    return layer;
}

async function replaceSelectionContent(base64Image) {
    const bounds = await getSelectionBounds();
    
    // Create layer from generated image
    const layer = await createLayerFromBase64(base64Image, "Generated Content");
    
    // Transform to fit selection
    if (bounds) {
        await batchPlay([
            {
                _obj: "transform",
                freeTransformCenterState: { 
                    _enum: "quadCenterState", 
                    _value: "QCSAverage" 
                },
                offset: {
                    _obj: "offset",
                    horizontal: { _unit: "pixelsUnit", _value: bounds.left },
                    vertical: { _unit: "pixelsUnit", _value: bounds.top }
                },
                width: { 
                    _unit: "percentUnit", 
                    _value: (bounds.width / layer.bounds.width) * 100 
                },
                height: { 
                    _unit: "percentUnit", 
                    _value: (bounds.height / layer.bounds.height) * 100 
                }
            }
        ], {});
    }
}

// ===== GEMINI API FUNCTIONS =====

async function generateImage(prompt, temperature = 0.9) {
    const requestBody = {
        contents: [{
            parts: [{ text: prompt }]
        }],
        generationConfig: {
            temperature: temperature,
            topK: 40,
            topP: 0.95,
            responseModalities: ["image"],
            responseImageType: "image/png"
        }
    };

    try {
        const response = await fetch(getGenerateEndpoint(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(`Gemini API Error: ${errorData.error?.message || response.statusText}`);
        }

        const data = await response.json();
        
        // Extract image data
        const imagePart = data.candidates?.[0]?.content?.parts?.find(p => p.inlineData);
        if (!imagePart) {
            throw new Error("No image generated in response");
        }

        return imagePart.inlineData.data;
    } catch (error) {
        throw new Error(`Failed to generate image: ${error.message}`);
    }
}

async function editImage(base64Image, prompt, temperature = 0.9) {
    const requestBody = {
        contents: [{
            parts: [
                { text: prompt },
                {
                    inline_data: {
                        mime_type: "image/png",
                        data: base64Image
                    }
                }
            ]
        }],
        generationConfig: {
            temperature: temperature,
            topK: 40,
            topP: 0.95,
            responseModalities: ["image"],
            responseImageType: "image/png"
        }
    };

    try {
        const response = await fetch(getGenerateEndpoint(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(requestBody)
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(`Gemini API Error: ${errorData.error?.message || response.statusText}`);
        }

        const data = await response.json();
        
        const imagePart = data.candidates?.[0]?.content?.parts?.find(p => p.inlineData);
        if (!imagePart) {
            throw new Error("No image generated in response");
        }

        return imagePart.inlineData.data;
    } catch (error) {
        throw new Error(`Failed to edit image: ${error.message}`);
    }
}

// ===== MAIN FUNCTIONS =====

async function generateFromPrompt(userPrompt) {
    if (!checkApiKey()) return false;
    
    try {
        await createHistoryState("Before Gemini Generation");
        
        console.log("Generating image with Gemini...");
        
        const generatedImage = await generateImage(userPrompt);
        
        console.log("Creating layer...");
        await createLayerFromBase64(
            generatedImage, 
            "Generated: " + userPrompt.substring(0, 30)
        );
        
        alert("✅ Success!\n\nImage generated and added as new layer");
        return true;
    } catch (error) {
        console.error("Error:", error.message);
        alert("❌ Error: " + error.message);
        return false;
    }
}

async function editSelection(userPrompt) {
    if (!checkApiKey()) return false;
    
    try {
        const hasSelection = await checkSelection();
        if (!hasSelection) {
            throw new Error("Please make a selection first!\n\n" +
                          "Tip: Press Q to enter Quick Mask mode,\n" +
                          "paint the area you want to edit,\n" +
                          "then press Q again.");
        }
        
        await createHistoryState("Before Gemini Edit");
        
        console.log("Capturing selection...");
        const selectionImage = await getSelectionAsBase64();
        
        console.log("Editing with Gemini...");
        const editedImage = await editImage(selectionImage, userPrompt);
        
        console.log("Applying result...");
        await replaceSelectionContent(editedImage);
        
        alert("✅ Success!\n\nSelection edited and replaced");
        return true;
    } catch (error) {
        console.error("Error:", error.message);
        alert("❌ Error: " + error.message);
        return false;
    }
}

async function transformSelection(transformation) {
    if (!checkApiKey()) return false;
    
    try {
        const hasSelection = await checkSelection();
        if (!hasSelection) {
            throw new Error("Please make a selection first");
        }
        
        await createHistoryState("Before Transform");
        
        console.log("Processing...");
        const selectionImage = await getSelectionAsBase64();
        
        const prompts = {
            blur: "Blur the background of this image while keeping the subject sharp and in focus",
            remove: "Remove the selected object from this image and fill with appropriate background that matches the surrounding area",
            enhance: "Enhance and improve this image with better lighting, colors, and overall quality",
            colorize: "Add natural, realistic color to this black and white or grayscale image",
            sharpen: "Make this image sharper and more detailed with enhanced clarity"
        };
        
        const prompt = prompts[transformation] || transformation;
        
        console.log("Transforming with Gemini...");
        const result = await editImage(selectionImage, prompt);
        
        console.log("Applying...");
        await replaceSelectionContent(result);
        
        alert(`✅ Success!\n\n${transformation} applied`);
        return true;
    } catch (error) {
        console.error("Error:", error.message);
        alert("❌ Error: " + error.message);
        return false;
    }
}

async function extendImage(direction = "all sides") {
    if (!checkApiKey()) return false;
    
    try {
        await createHistoryState("Before Extend");
        
        console.log("Getting context...");
        const docImage = await getDocumentAsBase64();
        
        console.log("Extending image...");
        const prompt = `Extend this image naturally on ${direction}, maintaining the same artistic style, composition, and visual consistency`;
        const extended = await editImage(docImage, prompt);
        
        console.log("Creating result...");
        await createLayerFromBase64(extended, "Extended Image");
        
        alert("✅ Success!\n\nImage extended");
        return true;
    } catch (error) {
        console.error("Error:", error.message);
        alert("❌ Error: " + error.message);
        return false;
    }
}

// ===== MAIN UI DIALOG =====

async function showMainDialog() {
    if (!app.activeDocument) {
        alert("Please open a document first!");
        return;
    }
    
    if (!checkApiKey()) {
        return;
    }
    
    const dialog = `
        <dialog id="mainDialog">
            <form method="dialog">
                <h1>🤖 Gemini Image Generator</h1>
                <hr/>
                
                <h2>Generate New Image</h2>
                <label>
                    <span>Prompt:</span>
                    <textarea id="generatePrompt" rows="3" placeholder="a serene mountain landscape at sunset..."></textarea>
                </label>
                <footer>
                    <button id="generateBtn" type="button" uxp-variant="cta">Generate Image</button>
                </footer>
                
                <hr/>
                
                <h2>Edit Selection</h2>
                <p style="font-size: 11px; color: #999;">Press Q → Paint area → Press Q → Run</p>
                <label>
                    <span>Edit Prompt:</span>
                    <textarea id="editPrompt" rows="3" placeholder="replace with a dramatic sunset sky..."></textarea>
                </label>
                <footer>
                    <button id="editBtn" type="button" uxp-variant="cta">Edit Selection</button>
                </footer>
                
                <hr/>
                
                <h2>Quick Transforms</h2>
                <p style="font-size: 11px; color: #999;">Make a selection first</p>
                <footer style="display: flex; gap: 5px; flex-wrap: wrap;">
                    <button id="blurBtn" type="button">Blur BG</button>
                    <button id="removeBtn" type="button">Remove</button>
                    <button id="enhanceBtn" type="button">Enhance</button>
                    <button id="colorizeBtn" type="button">Colorize</button>
                    <button id="sharpenBtn" type="button">Sharpen</button>
                </footer>
                
                <hr/>
                
                <h2>Extend Image</h2>
                <footer>
                    <button id="extendBtn" type="button">Extend All Sides</button>
                </footer>
                
                <hr/>
                
                <footer>
                    <button id="cancelBtn" type="submit" uxp-variant="primary">Close</button>
                </footer>
            </form>
        </dialog>
    `;
    
    document.body.innerHTML = dialog;
    
    const dialogElement = document.querySelector("#mainDialog");
    
    // Event handlers
    document.querySelector("#generateBtn").addEventListener("click", async () => {
        const prompt = document.querySelector("#generatePrompt").value;
        if (!prompt) {
            alert("Please enter a prompt!");
            return;
        }
        dialogElement.close();
        await generateFromPrompt(prompt);
    });
    
    document.querySelector("#editBtn").addEventListener("click", async () => {
        const prompt = document.querySelector("#editPrompt").value;
        if (!prompt) {
            alert("Please enter an edit prompt!");
            return;
        }
        dialogElement.close();
        await editSelection(prompt);
    });
    
    document.querySelector("#blurBtn").addEventListener("click", async () => {
        dialogElement.close();
        await transformSelection("blur");
    });
    
    document.querySelector("#removeBtn").addEventListener("click", async () => {
        dialogElement.close();
        await transformSelection("remove");
    });
    
    document.querySelector("#enhanceBtn").addEventListener("click", async () => {
        dialogElement.close();
        await transformSelection("enhance");
    });
    
    document.querySelector("#colorizeBtn").addEventListener("click", async () => {
        dialogElement.close();
        await transformSelection("colorize");
    });
    
    document.querySelector("#sharpenBtn").addEventListener("click", async () => {
        dialogElement.close();
        await transformSelection("sharpen");
    });
    
    document.querySelector("#extendBtn").addEventListener("click", async () => {
        dialogElement.close();
        await extendImage();
    });
    
    dialogElement.showModal();
}

// ===== RUN THE SCRIPT =====
showMainDialog();
```

---

## **How to Use:**

### **1. Setup:**
1. Open the script in a text editor
2. Replace `YOUR_API_KEY_HERE` with your actual Gemini API key from https://aistudio.google.com/app/apikey
3. Save the file as `GeminiPhotoshop.jsx`

### **2. Run in Photoshop:**
1. **File → Scripts → Browse...**
2. Select `GeminiPhotoshop.jsx`
3. Dialog appears with all options!

### **3. Usage Examples:**

**Generate New Image:**
- Type: "a cyberpunk city at night with neon lights"
- Click "Generate Image"

**Edit Selection (Inpainting):**
- Press `Q` (Quick Mask)
- Paint the area you want to change (black = selected)
- Press `Q` again
- Type: "replace with a dragon"
- Click "Edit Selection"

**Quick Transforms:**
- Make a selection
- Click any quick transform button

---

## **Features:**
✅ Complete UI dialog with all options
✅ Text-to-image generation
✅ Inpainting (edit selection)
✅ Quick transforms (blur, remove, enhance, etc.)
✅ Image extension
✅ History states (undo support)
✅ Error handling
✅ Progress messages in console

This is a single file script - no plugin installation needed!
