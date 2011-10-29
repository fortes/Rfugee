# Rfugee

Helper script for moving from Flickr to Picasa.

Downloads all your Flickr photos, copying Flickr metadata into the file:

* Caption
* Tags
* Latitude/Longitude
* Date Taken
* Privacy setting (as tags)

Stores files in Picasa-esqe file structure (YYYY-MM-DD folders).

## Warning

I have not tested this other than with my own photos. May or may not work with your photos. Use at your own risk.

## Requirements

0. Python
1. [ExifTool](http://www.sno.phy.queensu.ca/~phil/exiftool/)

## Instructions

1. Fill out `settings.example.py` and save as `settings.py`
2. Run `python rfugee.py` and watch it go (will take a long time if you have many photos)

## Future Ideas

* Figure out some sane way to preserve sets
* Export comments somehow
* Notes / People tags?

# License

MIT
