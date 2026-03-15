import requests
import tarfile


URL = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/20260314-001002/event.tar.xz"

resp = requests.get(url=URL, stream=True)

resp.raw.decode_content = True

with tarfile.open(fileobj=resp.raw, mode="r|xz") as tar: 
    
    for member in tar:
        
        if member.name == 'mbdump/event':
            file = tar.extractfile(member)
            chunk = []
            chunk_size = 10000
            chunk_num = 0
            
            for i, line in enumerate(file):
                text = line.decode().strip()
                chunk.append(text)

                if len(chunk) >= chunk_size:
                    payload = "\n".join(chunk) + "\n"
                    print(f"Chunk {chunk_num} ready, {len(chunk)} lines, {len(payload)} bytes")
                    chunk = []
                    chunk_num += 1

            if chunk:
                payload = "\n".join(chunk) + "\n"
                print(f"Chunk {chunk_num} ready, {len(chunk)} lines, {len(payload)} bytes")
                chunk = []
