import settings

import json
import os.path
import sqlite3
import sys
import time
import urllib2
import urlparse
import subprocess
import shlex
import pipes

sys.path.insert(1,'lib')
import flickrapi

def get_flickr():
    """Connect to flickr, prompting the user to authorize if necessary"""
    sys.stdout.write("Connecting to Flickr...\n");
    flickr = flickrapi.FlickrAPI(settings.api_key, settings.secret,
                                 format='json')

    # Check for permissions
    (token, frob) = flickr.get_token_part_one(perms='read')

    if not token:
        raw_input('Press ENTER once you have authorized the program')

    # Complete
    flickr.get_token_part_two((token, frob))

    return flickr

def get_database():
    """Fetch and/or create the database for holding photo info"""
    existed = os.path.exists(settings.database_filename)
    conn = sqlite3.connect(settings.database_filename)

    if existed:
        sys.stdout.write("Using existing database: %s\n" %
                         settings.database_filename)
        return conn

    else:
        sys.stdout.write("Creating new database: %s\n" %
                         settings.database_filename)
        # Create tables
        conn.execute('CREATE TABLE info(key text, value text)')
        conn.execute('''CREATE TABLE photos(id text,
                                            img_url text,
                                            media text,
                                            json_data text,
                                            downloaded integer,
                                            metadata integer,
                                            saved_path text
                    )''')
        conn.commit()

        return conn

def populate_photos(flickr, db):
    """Return the total number of photos that the user has"""
    # Do one quick request just to get the list of total photos
    sys.stdout.write("Fetching list of photos from Flickr\n")

    # Flickr begins at 1
    page_number = 1
    total_pages = None
    photos = []

    # Flags for the metadata we need
    extras = 'date_taken,original_format,geo,tags,machine_tags,views,media,description,url_o'

    # Query flickr a bunch of times to get the info we need
    while not total_pages or page_number <= total_pages:
        sys.stdout.write("\rFetching page %s of %s ...      " % (page_number, total_pages or '?'))
        sys.stdout.flush()

        search_res = json.loads(
            flickr.photos_search(user_id=settings.user_id, per_page='100',
                                 page=page_number, nojsoncallback=True,
                                 extras=extras)
        )

        if not total_pages:
            total_pages = search_res['photos']['pages']

        pics_arr = search_res['photos']['photo']
        pic_tuples = [(photo['id'], photo['url_o'], photo['media'], json.dumps(photo)) for photo in pics_arr]

        # Write records into database
        db.executemany('INSERT INTO photos(id, img_url, media, json_data) VALUES(?,?,?,?)', pic_tuples)

        # Increment
        page_number += 1

    sys.stdout.write("\n\rFetched all %s pages of info      \n" % page_number)
    sys.stdout.flush()

    # Save out to disk
    db.commit()

    return photos

def get_photo_list(flickr, db):
    """Returns an array of photos that need to be downloaded"""
    photos = db.execute('SELECT * FROM photos WHERE downloaded IS NULL').fetchall()

    if len(photos):
        return photos

    # If this is the first time, then there might not have been any photos
    all_photos = db.execute('SELECT * FROM photos').fetchall()

    if len(all_photos):
        # Great, photos have been fetched before, so we're all good
        return []

    return populate_photos(flickr, db)

def download_photos(photos, db):
    """Downloads a list of photos to disk"""

    sys.stdout.write("%s photos to download\n" % len(photos))
    sys.stdout.flush()

    photo_count = len(photos)

    for index, photo in enumerate(photos):
        json_info = json.loads(photo[3])
        url = photo[1] # URL
        filename = os.path.basename(urlparse.urlparse(url).path)
        folderpath = os.path.join(settings.photo_root, json_info['datetaken'][:10])
        # Create folder, if not there
        if not os.path.exists(folderpath):
            os.makedirs(folderpath)
        filepath = os.path.join(folderpath, filename)
        sys.stdout.write("\rDownloading file %s of %s [%s]" % (index + 1, photo_count, filepath))
        sys.stdout.flush()

        try:
            # Download File
            remote_image = urllib2.urlopen(url)
            image_data = remote_image.read()
            # Save File
            image_file = open(filepath, 'wb')
            image_file.write(image_data)
            image_file.close()
            # Save path into db and mark as downloaded
            db.execute('UPDATE photos SET saved_path=?,downloaded=1 WHERE id=?', (filepath, photo[0]))
            db.commit()

        except:
            sys.stdout.write("\r")
            sys.stdout.flush()
            sys.stderr.write("Download failed for: %s\n" % url)
            sys.stderr.flush()

    sys.stdout.write("\n%s photos downloaded\n" % len(photos))

base58letters = '123456789abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ'
base58len = len(base58letters)

def base58encode(id):
    """
    Encoding for Flickr short urls described here:
    http://www.flickr.com/groups/api/discuss/72157616713786392/
    """
    str = ''

    while id >= base58len:
        div, mod = divmod(id, base58len)
        str = base58letters[mod] + str
        id = int(div)

    if (id):
        str = base58letters[id] + str

    return str

def add_metadata(db):
    # Only get photos w/o metadata written
    photos = db.execute('SELECT * FROM photos WHERE metadata IS NULL').fetchall()

    photo_count = len(photos)
    if not photo_count:
        print 'No photos need metadata'

    print "%s photos need metadata" % photo_count
    for index, photo in enumerate(photos):
        metadata = json.loads(photo[3])
        # Becomes Caption-Abstract in EXIF
        title = metadata['title']
        if metadata['description'] and metadata['description']['_content']:
            title += ": " + metadata['description']['_content']
        # Keywords (comma-sep)
        tags = metadata['tags'].split(' ')
        # ID in comment
        id = photo[0]
        # URL in Source
        short_url = "http://flic.kr/p/%s" % base58encode(int(id))
        # DateTimeOriginal
        date_taken = metadata['datetaken'].replace('-', ':')
        # Latitude & Longitude
        latitude = metadata['latitude']
        longitude = metadata['longitude']

        sys.stdout.write("\rWriting metadata %s of %s [%s]                    " % (index + 1, photo_count, photo[6]))
        sys.stdout.flush()

        # Run exiftool command
        cmd = "exiftool -overwrite_original_in_place"
        if title:
            cmd += " -description=%s " % pipes.quote(title)
        if tags and len(tags):
            for tag in tags:
                cmd += """ -keywords=%s """ % pipes.quote(tag)
        cmd += """ -Source=%s """ % pipes.quote(short_url)
        cmd += """ -Comment="Flickr ID: %s" """ % id
        cmd += """ -DateTimeOriginal=%s """ % pipes.quote(date_taken)
        if latitude and longitude:
            if latitude > 0:
                cmd += """ -gps:GPSLatitudeRef="N" """
            else:
                cmd += """ -gps:GPSLatitudeRef="S" """
            if longitude > 0:
                cmd += """ -gps:GPSLongitudeRef="E" """
            else:
                cmd += """ -gps:GPSLongitudeRef="W" """

            cmd += """ -gpslatitude="%s" """ % abs(latitude)
            cmd += """ -gpslongitude="%s" """ % abs(longitude)

        # Privacy
        if metadata['ispublic']:
            cmd += ' -keywords="privacy:public"'
        elif not (metadata['isfriend'] or metadata['isfamily']):
            cmd += ' -keywords="privacy:private"'
        else:
            if metadata['isfriend']:
                cmd += ' -keywords="privacy:friend"'
            if metadata['isfamily']:
                cmd += ' -keywords="privacy:family"'

        # Add filename
        cmd += """ %s """ % photo[6]

        # Run command
        try:
            fnull = open(os.devnull, 'w')
            subprocess.call(cmd, shell=True, stdout=fnull, stderr=fnull)
            fnull.close()

            # Save path into db and mark as metadata'd
            db.execute('UPDATE photos SET metadata=1 WHERE id=?', [photo[0]])
            db.commit()
        except sqlite3.ProgrammingError as e:
            print e
            print photo[0]
        except:
            sys.stderr.write("\rMetadata failed for: %s                \n" % photo[6])
            sys.stderr.write("%s\n\r" % sys.exc_info()[0])
            sys.stderr.flush()

if __name__ == '__main__':
    # Connect to Flickr
    flickr = get_flickr()

    # Get a connection to the database, creating one if it does not exist
    db = get_database()

    # Retrieve list of photos that still need to be downloaded
    photos = get_photo_list(flickr, db)

    # Do the actual downloading
    if len(photos):
        download_photos(photos, db)
    else:
        print "No photos left to download"

    # Now add metadata
    add_metadata(db)

    db.close()

    print "\nCompleted"
