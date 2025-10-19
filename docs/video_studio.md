# Video Studio Documentation

## Overview

The Video Studio is a dedicated interface for creating short-form videos with AI-powered text-to-speech narration, background videos, subtitles, and music. It provides a professional, streamlined workflow for video content creation.

## Accessing the Studio

- **From AI Content page:** Click the "Launch Studio →" button at the top
- **Direct URL:** Navigate to `/ui/video-studio`

## Interface Layout

The Video Studio uses a three-panel layout optimized for video production:

### Left Sidebar: Project Management
- **New Project Button:** Create a new video project
- **Project List:** View all your projects with status badges
  - 🟢 **READY:** Video has been successfully rendered
  - 🟡 **RENDERING:** Video is currently being generated
  - ⚪ **DRAFT:** Project created but not yet rendered
  - 🔴 **ERROR:** Rendering failed

### Center Workspace: Preview & Timeline
- **Video Preview Canvas:** Large 9:16 aspect ratio preview area
  - Shows placeholder when no video is rendered
  - Displays rendered video with playback controls
- **Action Buttons:**
  - 🎥 **Render Video:** Generate the final video
  - ▶️ **Quick Preview:** (Future feature)
  - 💾 **Save:** Save current project settings
- **Timeline:** Visual representation of video content (placeholder for future enhancements)

### Right Panel: Settings & Controls

#### 🎯 Project Settings
- **Video Title:** The title displayed in the video (required)
- **Script / Narration:** The text that will be converted to speech (required)

#### 🎨 Background
- **Static Title:** Simple title card with gradient background
- **Dynamic Backgrounds:** Video backgrounds for more engaging content
  - Click **Refresh** to reload background list
  - Click **Generate Samples** to create sample backgrounds using ffmpeg
  - Select any background by clicking its thumbnail

#### 🎙️ Voice & Audio
- **Voice Selection:** Choose from available TTS voices
  - Click 🔄 to refresh voice list
  - Click **Preview Voice** to hear a sample
- **Speech Rate:** Adjust narration speed (120-220 wpm)
- **Background Music:** Toggle to add ambient music
- **Music Volume:** Control music loudness (0.0-1.0)
- **Duck Music:** Automatically lower music when narration plays

#### 📝 Subtitles & Overlays
- **Burn Subtitles:** Add hardcoded captions to video
- **Show Title Overlay:** Display title text over video
- **Minimum Duration:** Pad video with silence to reach target length

## Workflow

### Creating Your First Video

1. **Start a Project**
   ```
   Click "New Project" in the sidebar
   ```

2. **Add Content**
   ```
   - Enter a catchy title
   - Write your script (aim for 30-60 seconds of narration)
   ```

3. **Customize Appearance**
   ```
   - Select a background (or use Static Title)
   - Choose subtitle and overlay options
   ```

4. **Configure Audio**
   ```
   - Select a voice that fits your content
   - Preview the voice with sample text
   - Adjust speech rate if needed
   - Optionally add background music
   ```

5. **Render**
   ```
   Click "Render Video" and wait for processing
   Video preview will appear in the canvas when ready
   ```

### Managing Multiple Projects

- **Switch Projects:** Click any project card in the sidebar
- **Active Project:** Highlighted with blue border
- **Status Tracking:** Color-coded badges show project state
- **Auto-Save:** Changes are saved when you click "Save" or switch projects

## Technical Details

### Video Specifications
- **Format:** MP4 (H.264 video, AAC audio)
- **Aspect Ratio:** 9:16 (vertical/portrait)
- **Resolution:** 720x1280 pixels
- **Frame Rate:** 30 fps

### TTS (Text-to-Speech)
- **Engine:** pyttsx3 (offline) or espeak-ng
- **Voice Selection:** System-dependent voices
- **Speech Rate:** Adjustable 120-220 words per minute
- **Language Support:** Depends on installed voices

### Background Videos
- **Location:** Stored in `MEDIA_DIR/backgrounds/`
- **Formats:** MP4, MOV, MKV, WebM
- **Duration:** Automatically looped to match audio length
- **Generation:** Created using ffmpeg lavfi filters

### Background Music
- **Generation:** Procedural using ffmpeg audio filters
- **Type:** Pink noise shaped with lowpass/highpass
- **Ducking:** Sidechaincompress filter when narration plays
- **Volume:** Adjustable 0.0-1.0 (default 0.15)

### Subtitle Generation
- **Format:** SRT (SubRip)
- **Timing:** Auto-distributed across video duration
- **Rendering:** Burned into video using ffmpeg subtitles filter
- **Font:** DejaVu Sans Bold

## API Endpoints Used

The Video Studio interacts with these backend endpoints:

- `GET /ui/video-studio` - Loads the interface
- `GET /ai/voices` - Lists available TTS voices
- `GET /ai/voices?refresh=true` - Refreshes voice cache
- `POST /ai/voices/preview` - Generates voice sample
- `GET /ai/video/backgrounds` - Lists background videos
- `POST /ai/video/backgrounds/seed` - Generates sample backgrounds
- `POST /ai/video` - Renders the final video
- `GET /media/{filename}` - Serves rendered videos

## Troubleshooting

### No Voices Available
**Problem:** Voice dropdown shows "(default)" only

**Solution:**
```bash
# Install espeak-ng on your system
sudo apt-get install -y espeak-ng

# Or on the Docker container
docker compose exec backend apt-get install -y espeak-ng

# Then click "Refresh voices" in the studio
```

### No Backgrounds Available
**Problem:** Only "Static Title" option shown

**Solution:**
```
Click "Generate Samples" button to create sample backgrounds
This uses ffmpeg to generate colorful animated backgrounds
```

### Video Rendering Fails
**Problem:** "Render Video" fails with error

**Possible causes:**
- ffmpeg not installed
- Title or script is empty
- TTS engine failed
- Insufficient disk space

**Check logs:**
```bash
docker compose logs backend
```

### Voice Preview Not Working
**Problem:** Preview button does nothing

**Solution:**
- Ensure espeak-ng or pyttsx3 is installed
- Check browser audio permissions
- Try a different voice from the dropdown

## Future Enhancements

Planned features for future releases:

- **Project Persistence:** Save projects to database
- **Video Templates:** Pre-configured project templates
- **Advanced Timeline:** Multi-track editing with trim/split
- **Scene Management:** Multiple scenes per video
- **Asset Library:** Upload and manage custom backgrounds/music
- **Batch Rendering:** Queue multiple videos
- **Export Presets:** Platform-specific optimizations (TikTok, Instagram, YouTube)
- **Collaboration:** Share projects with team members
- **Analytics:** Track video performance

## Tips for Best Results

1. **Script Length:** Aim for 100-250 words (30-90 seconds)
2. **Voice Selection:** Preview multiple voices to find the best fit
3. **Speech Rate:** 160 is natural; slower (140) for tutorials, faster (180) for excitement
4. **Background Choice:** Match background energy to content tone
5. **Music Volume:** Keep low (0.1-0.2) to avoid overpowering narration
6. **Subtitles:** Always enable for better accessibility and engagement
7. **Title Overlay:** Useful for branding but can be distracting

## Performance Notes

- **Rendering Time:** Typically 5-30 seconds depending on script length
- **Storage:** Videos average 5-15 MB for 30-60 second clips
- **Concurrent Renders:** One render at a time per user (client-side limitation)
- **Browser Requirements:** Modern browser with ES6+ support

## Support

For issues or feature requests, please:
1. Check this documentation
2. Review backend logs: `docker compose logs backend`
3. Open an issue on GitHub with reproduction steps
