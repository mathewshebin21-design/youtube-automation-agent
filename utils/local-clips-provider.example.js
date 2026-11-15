// Example LocalClipsProvider for GTA 6
// Place your own captured clips in ./gta6-clips/ and a manifest.json

const fs = require('fs').promises;
const path = require('path');

class LocalClipsProvider {
  constructor(clipsFolder = './gta6-clips') {
    this.clipsFolder = clipsFolder;
  }

  async listClips() {
    try {
      const manifestPath = path.join(this.clipsFolder, 'manifest.json');
      const raw = await fs.readFile(manifestPath, 'utf8');
      return JSON.parse(raw);
    } catch (err) {
      return [];
    }
  }

  async getClip(id) {
    const clips = await this.listClips();
    return clips.find(c => c.id === id) || null;
  }
}

module.exports = { LocalClipsProvider };
