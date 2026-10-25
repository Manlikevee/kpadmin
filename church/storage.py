from pathlib import Path
from cloudinary_storage.storage import MediaCloudinaryStorage


class StoryMediaCloudinaryStorage(MediaCloudinaryStorage):
    VIDEO_EXTENSIONS = {
        ".mp4",
        ".mov",
        ".webm",
        ".m4v",
        ".avi",
        ".mkv",
        ".mpeg",
        ".mpg",
        ".3gp",
    }

    def _get_resource_type(self, name):
        extension = Path(name).suffix.lower()

        if extension in self.VIDEO_EXTENSIONS:
            return "video"

        return "image"