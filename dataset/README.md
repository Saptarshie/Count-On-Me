# 📁 Dataset Directory

This folder contains face images organized by student name.

## Structure

```
dataset/
├── Student_Name_1/
│   ├── center_20260222_163000_000001.jpg
│   ├── left_20260222_163005_000002.jpg
│   ├── right_20260222_163010_000003.jpg
│   └── ...
├── Student_Name_2/
│   ├── center_20260222_164000_000001.jpg
│   └── ...
```

## Creating Dataset

### Automatic Capture (Recommended)

```bash
python collect_dataset.py --name "Student Name"
```

**Features:**
- Guided pose instructions
- Quality indicators (lighting, focus, centering)
- Auto-capture mode available
- Saves images with pose labels

### Manual Collection

1. Create a folder with the student's name
2. Add 10-20 face images
3. Ensure varied angles and expressions

## 🧠 Dataset Collection Rules

For best recognition accuracy:

1. **Move head slightly left-right** - Capture side profiles
2. **Look up-down** - Capture different vertical angles  
3. **Blink naturally** - For liveness detection training
4. **Change expressions** - Neutral, smile, serious
5. **Vary lighting** - Different times of day, locations
6. **Remove masks/glasses** - Clear face visibility required

## Image Requirements

| Attribute | Requirement |
|-----------|-------------|
| Format | JPG, PNG, BMP |
| Face Size | 15-30% of frame |
| Resolution | At least 640x480 |
| Quality | Sharp, well-lit |
| Per Person | 10-20 images recommended |

## After Collection

Run encoding to process the dataset:

```bash
python main.py --encode
```

This creates `models/encodings.pkl` with face embeddings.
