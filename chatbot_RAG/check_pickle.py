import pickle


with open("vectorless_chunks.pkl", "rb") as f:
    data = pickle.load(f)

print("Main Keys:")
print(data.keys())


print("\nStored Sessions:")
print(data["docs"].keys())

for session_id, docs in data["docs"].items():

    print("\n======================")
    print("Session ID:", session_id)
    print("Total Chunks:", len(docs))

    if docs:
        print("\nFirst Chunk Content:\n")
        print(docs[0].page_content)

        print("\nMetadata:\n")
        print(docs[0].metadata)


print("\n======================")
print("BM25 Models:")

for session_id, bm25 in data["bm25_models"].items():
    print(session_id, type(bm25))