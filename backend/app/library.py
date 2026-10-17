from dataclasses import dataclass


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    path: str  # Object path in the media bucket
    duration: int  # Seconds
    synopsis: str
    credit: str


# Creative Commons films from the Blender Foundation (attribution required).
LIBRARY: dict[str, Video] = {
    v.id: v
    for v in [
        Video(
            id="tears-of-steel",
            title="Tears of Steel",
            path="library/tears-of-steel.mp4",
            duration=734,
            synopsis=(
                "Sci-fi short: in a future Amsterdam, a group of warriors and scientists "
                "try to save the world from destructive robots by restaging a breakup."
            ),
            credit="(CC) Blender Foundation | mango.blender.org — CC BY 3.0",
        ),
        Video(
            id="sintel",
            title="Sintel",
            path="library/sintel.mp4",
            duration=888,
            synopsis=(
                "Fantasy short: a lonely girl named Sintel befriends a baby dragon, "
                "and searches the world for it after it is taken from her."
            ),
            credit="(CC) Blender Foundation | durian.blender.org — CC BY 3.0",
        ),
    ]
}
