// GTA 6 Private Upload Guard
// Forces all uploads to private unless an explicit human-approved override is set.

function enforcePrivateUpload(videoMetadata, options = {}) {
  const forcePrivate = process.env.GTA6_FORCE_PRIVATE !== 'false';
  const hasHumanOverride = options.humanApprovedPublic === true && options.approvalToken;

  if (forcePrivate && !hasHumanOverride) {
    videoMetadata.status = videoMetadata.status || {};
    videoMetadata.status.privacyStatus = 'private';
    // Remove publishAt so it does not auto-go public
    delete videoMetadata.status.publishAt;
    return {
      ...videoMetadata,
      _gta6Guard: 'private-forced'
    };
  }
  return videoMetadata;
}

module.exports = { enforcePrivateUpload };
