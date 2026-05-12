import pickle

with open("vectorless_chunks.pkl", "rb") as f:

    data = pickle.load(f)

print(type(data))

print(data[:2])