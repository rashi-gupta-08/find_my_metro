"""Execute exported regression trees with scikit-learn's float32 input semantics."""
import struct


def predict_forest(forest, values):
    features=[struct.unpack('<f',struct.pack('<f',value))[0] for value in values]
    predictions=[]
    for tree in forest:
        index=0
        while tree['left'][index]!=-1:
            index=tree['left'][index] if features[tree['feature'][index]]<=tree['threshold'][index] else tree['right'][index]
        predictions.append(tree['value'][index])
    return sum(predictions)/len(predictions)
