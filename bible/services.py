"""Bible translation file operations shared by the dashboard and the mobile API."""
import logging

logger = logging.getLogger(__name__)


def destroy_remote_file(name):
    """Remove a stored raw file from Cloudinary (raises on failure)."""
    from cloudinary import uploader

    uploader.destroy(name, resource_type="raw", invalidate=True)


def replace_translation(translation, *, name, upload, user):
    """Swap in a new JSON file (and optionally rename) for an existing translation.

    The new file is saved first; the old Cloudinary asset is removed only after
    that succeeds, and a failure to remove it is logged rather than raised, so
    the replacement is never lost because of a clean-up problem.
    """
    old_file = translation.file.name if translation.file else None
    translation.name = name.strip().upper()
    translation.file = upload
    translation.size_in_bytes = upload.size
    translation.uploaded_by = user
    translation.save()
    if old_file and old_file != translation.file.name:
        try:
            destroy_remote_file(old_file)
        except Exception:
            logger.warning("Could not delete the old Bible file %s", old_file, exc_info=True)
    return translation


def delete_translation(translation):
    """Delete the remote file first, then the row (nothing is lost if the remote call fails)."""
    if translation.file:
        destroy_remote_file(translation.file.name)
    translation.delete()
