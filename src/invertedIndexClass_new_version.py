import os
import shutil
import json
import heapq
import nltk
import numpy as np
from collections import defaultdict, Counter
from nltk.stem.snowball import SnowballStemmer
import pandas as pd

current_dir = os.path.abspath(os.path.dirname(__file__))
base_path = os.path.join(current_dir, os.pardir, "data")
stoplist_path = os.path.join(base_path, "stoplist.txt")
temp_index_dir = os.path.join(current_dir, "temp_indexes")

nltk.download("punkt")
with open(stoplist_path, encoding="utf-8") as file:
    stoplist = [line.rstrip().lower() for line in file]

if not os.path.exists(temp_index_dir):
    os.makedirs(temp_index_dir)


class InvertedIndex:
    def __init__(self, file):
        self.path_docs = file
        self.block_size = 100  # Número de documentos por bloque
        self.doc_count = 1000  # numero de documentos
        # self.stemmer = SnowballStemmer("spanish")
        self.stemmer = SnowballStemmer("english")
        if (False):
            self.building()
        self.chuks_number = 0

    def build_index(self):
        # SPIMI
        chunk_iter = pd.read_csv(self.path_docs, chunksize=self.block_size)
        # tem dir para almacenar los bloques
        temp_block_dir = os.path.join(temp_index_dir, "blocks")
        if not os.path.exists(temp_block_dir):
            os.makedirs(temp_block_dir)

        for i, chunk in enumerate(chunk_iter):
            partial_index = defaultdict(lambda: defaultdict(int))
            len_chunk = len(chunk["text"])
            for doc_id, document in enumerate(chunk["text"]):
                processed = self.preprocess(document)
                for term, tf in processed.items():
                    # almacenar {term: {doc_id: tf}}
                    if term not in partial_index:
                        partial_index[term] = {(i * len_chunk) + doc_id: tf}
                    else:
                        partial_index[term][doc_id] = tf

            # ordenar el índice parcial por término  y cada lista de postings por doc_id
            partial_index = {
                term: dict(sorted(postings.items()))
                for term, postings in sorted(partial_index.items())
            }

            # Escribir el índice parcial en memoria secundaria as a JSON file
            with open(
                os.path.join(temp_block_dir, f"block_{i}.json"), "w", encoding="utf-8"
            ) as file:
                json.dump(partial_index, file, indent=4)

            self.doc_count += len_chunk
            self.chuks_number = i + 1

        self.merge_blocks(temp_block_dir)
        # delete blocks carpeta entera
        if os.path.exists(temp_block_dir):
            shutil.rmtree(temp_block_dir)

    def merge_blocks(self, temp_block_dir):
        temp_index_dir_pages = os.path.join(temp_index_dir, "invert_index")
        if not os.path.exists(temp_index_dir_pages):
            os.makedirs(temp_index_dir_pages)

        # Merge blocks into a single index por partes:
        min_heap = []
        json_files = [
            os.path.join(temp_block_dir, f"block_{i}.json")
            for i in range(self.chuks_number)
        ]
        file_terms = [self.load_next_term(filename, 1) for filename in json_files]
        file_pointers = [1 for i in range(self.chuks_number)]

        # Initialize heap with the first term from each block
        for i in range(self.chuks_number):
            term = list(file_terms[i].keys())[0]
            heapq.heappush(min_heap, (term, i))

        final_terms = defaultdict(lambda: defaultdict(int))

        index_page = 0
        while min_heap:
            term, i = heapq.heappop(min_heap)

            # Extract postings correctly
            postings = file_terms[i][term]

            if term in final_terms:
                final_terms[term].update(postings)
            else:
                final_terms[term] = postings

            # Load next term from the block used
            file_pointers[i] += 1
            new_term = self.load_next_term(json_files[i], file_pointers[i])
            if new_term != None:
                new_term_key = list(new_term.keys())[0]
                heapq.heappush(min_heap, (new_term_key, i))
                file_terms[i] = new_term

            # Write the final index to disk
            if len(final_terms) >= self.block_size:
                while min_heap:
                    temp_t, temp_i = heapq.heappop(min_heap)
                    if temp_t != term:
                        heapq.heappush(min_heap, (temp_t, temp_i))
                        break

                    # Write the partial index to disk
                    final_terms[term].update(file_terms[temp_i][temp_t])
                    file_pointers[temp_i] += 1
                    new_term = self.load_next_term(
                        json_files[temp_i], file_pointers[temp_i]
                    )
                    if new_term != None:
                        new_term_key = list(new_term.keys())[0]
                        heapq.heappush(min_heap, (new_term_key, temp_i))
                        file_terms[temp_i] = new_term

                # Sort postings by doc_id
                final_terms = {
                    term: postings for term, postings in sorted(final_terms.items())
                }

                # Escribir el índice parcial en disco
                # self.write_json_file(dict(final_terms), os.path.join(temp_index_dir, "index_build.json"))
                index_page += 1
                file_name = os.path.join(
                    temp_index_dir_pages, f"index_{index_page}.json"
                )
                self.write_file(dict(final_terms), file_name)
                final_terms.clear()

        if final_terms:
            index_page += 1
            file_name = os.path.join(temp_index_dir_pages, f"index_{index_page}.json")
            final_terms = {
                term: dict(sorted(postings.items()))
                for term, postings in sorted(final_terms.items())
            }
            self.write_file(dict(final_terms), file_name)

    def load_next_term(self, filename, num_term):
        with open(filename, "r") as file:
            data = json.load(file)

        count = 0
        for key, value in data.items():
            count += 1
            if count == num_term:
                return {key: value}
        return None

    def write_json_file(self, data, filename):
        data_str = json.dumps(data, indent=4)

        # verificar si existe el archivo
        if not os.path.exists(filename):
            with open(filename, "w") as file:
                file.write(data_str)
        else:
            with open(filename, "r+") as file:
                file.seek(0, 2)  # mover el puntero al final del archivo

                file.seek(file.tell() - 1)
                file.write(",")
                file.write(data_str[1:-1])  # Eliminar {}
                file.write("}")

    def write_file(self, data, filename):
        with open(filename, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)

    def preprocess(self, text):
        tokens = nltk.word_tokenize(text.lower())
        tokens = [w for w in tokens if w not in stoplist and w.isalnum()]
        result = Counter([self.stemmer.stem(w) for w in tokens])
        return result  # {word: frequency}

    def building(self):
        self.build_index()
        self.compute_tf_idf_and_lengths()

    def compute_tf_idf_and_lengths(self):
        temp_index_dir_pages = os.path.join(temp_index_dir, "invert_index")
        if not os.path.exists(temp_index_dir_pages):
            print("Error: invert_index not fount")

        temp_docs_dir = os.path.join(temp_index_dir, "temp_docs")
        if not os.path.exists(temp_docs_dir):
            os.makedirs(temp_docs_dir)

        term_doc_count = defaultdict(int)
        tf_idf = defaultdict(lambda: defaultdict(float))
        doc_lengths = defaultdict(float)

        for i in range(1, len(os.listdir(temp_index_dir_pages)) + 1):
            # if file.startswith("index_"):
            file = os.path.join(temp_index_dir_pages, f"index_{i}.json")
            with open(
                os.path.join(temp_index_dir_pages, file), "r", encoding="utf-8"
            ) as f:
                partial_index = json.load(f)
                for term, postings in partial_index.items():
                    term_doc_count[term] += len(postings)
                    for doc_id, tf in postings.items():
                        tf_idf[term][doc_id] = (1 + np.log10(tf)) * self.log_frec_idf(
                            self.doc_count, term_doc_count[term]
                        )
                        # doc_lengths[doc_id] += tf_idf[term][doc_id] ** 2
                        if doc_id in doc_lengths:
                            doc_lengths[doc_id] += tf_idf[term][doc_id] ** 2
                        else:
                            doc_lengths[doc_id] = tf_idf[term][doc_id] ** 2

            # write update page
            self.write_file(dict(tf_idf), file)
            tf_idf.clear()
            term_doc_count.clear()

            # write docs_id: partial_sum(tf-idf**2)
            doc_lengths = {
                int(doc_id): sum_tfidf for doc_id, sum_tfidf in doc_lengths.items()
            }
            doc_lengths = {
                doc_id: sum_tfidf for doc_id, sum_tfidf in sorted(doc_lengths.items())
            }
            file_docs = os.path.join(temp_docs_dir, f"docpage_{i}.json")
            self.write_file(dict(doc_lengths), file_docs)
            doc_lengths.clear()

        # Merge docs_id

        self.merge_docs_lengths(temp_docs_dir)

        # delete blocks carpeta entera
        if os.path.exists(temp_docs_dir):
            shutil.rmtree(temp_docs_dir)

    def log_frec_idf(self, N, df):
        if df > 0:
            return np.log10(N / df)
        return 0

    def retrieve(self, query, k):
        query_vector = self.preprocess(query) # {term: tf}
        # query_tf_idf = {term: (1 + np.log10(tf)) for term, tf in query_vector.items()}
        # query_norm = np.sqrt(sum(val**2 for val in query_tf_idf.values()))

        # with open(
        #     os.path.join(temp_index_dir, "tf_idf.json"), "r", encoding="utf-8"
        # ) as file:
        #     tf_idf = json.load(file)

        # with open(
        #     os.path.join(temp_index_dir, "doc_lengths.json"), "r", encoding="utf-8"
        # ) as file:
        #     doc_lengths = json.load(file)

        term_doc_count = defaultdict(int)
        query_tf_idf = defaultdict(float)
        scores = defaultdict(float)

        temp_index_dir_pages = os.path.join(temp_index_dir, "invert_index")
        if not os.path.exists(temp_index_dir_pages):
            print("Error: invert_index not fount")

        for i in range(1, len(os.listdir(temp_index_dir_pages)) + 1):
            # if file.startswith("index_"):
            file = os.path.join(temp_index_dir_pages, f"index_{i}.json")
            with open( os.path.join(temp_index_dir_pages, file), "r", encoding="utf-8" ) as f:
                tf_idf = json.load(f)
                # term_doc_count = {term: len(tf_idf[term]) for term in tf_idf}
                for term in query_vector.keys():
                    if term in tf_idf:
                        term_doc_count[term] = len(tf_idf[term])
                        query_tf_idf[term] = 1 + np.log10(query_vector[term])*self.log_frec_idf(self.doc_count, term_doc_count[term])
                    
                        for doc_id, tf_idf_val in tf_idf[term].items():
                            if doc_id in scores:
                                scores[doc_id] += query_tf_idf[term] * tf_idf_val
                            else:
                                scores[doc_id] = query_tf_idf[term] * tf_idf_val

        # query_tf_idf = {
        #     term: (1 + np.log10(tf))
        #     * self.log_frec_idf(self.doc_count, term_doc_count.get(term, 0))
        #     for term, tf in query_vector.items()
        # }

        query_norm = np.sqrt(sum(val**2 for val in query_tf_idf.values()))
        temp_docs_pages = os.path.join(temp_index_dir, "docs_norms")
        if not os.path.exists(temp_docs_pages):
            print("Error: docs_norms not fount")

        for i in range(1, len(os.listdir(temp_docs_pages)) + 1):
            # if file.startswith("index_"):
            file = os.path.join(temp_docs_pages, f"docs_norms_{i}.json")
            with open( os.path.join(temp_docs_pages, file), "r", encoding="utf-8" ) as f:
                doc_lengths = json.load(f)
                for doc_id in scores:
                    if doc_id in doc_lengths:
                        scores[doc_id] /= query_norm * doc_lengths[doc_id]

        sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return sorted_scores[:k] if sorted_scores else None

    def merge_docs_lengths(self, temp_docs_dir):
        temp_docs_pages = os.path.join(temp_index_dir, "docs_norms")
        if not os.path.exists(temp_docs_pages):
            os.makedirs(temp_docs_pages)

        # Merge blocks into a single index por partes:
        min_heap = []
        json_files = [
            os.path.join(temp_docs_dir, f"docpage_{i+1}.json")
            for i in range(len(os.listdir(temp_docs_dir)))
        ]
        file_terms = [
            self.convert_key_to_int(self.load_next_term(filename, 1))
            for filename in json_files
        ]
        file_pointers = [1 for _ in range(len(os.listdir(temp_docs_dir)))]

        # Initialize heap with the first term from each block
        for i in range(len(os.listdir(temp_docs_dir))):
            term = file_terms[i]
            heapq.heappush(min_heap, (list(term.keys())[0], i))

        final_terms = defaultdict(float)
        index_page = 0
        while min_heap:
            doc, i = heapq.heappop(min_heap)

            # extraer correctamente
            tf_idf = file_terms[i][doc]

            if doc in final_terms:
                final_terms[doc] += tf_idf
            else:
                final_terms[doc] = tf_idf

            file_pointers[i] += 1
            new_term = self.load_next_term(json_files[i], file_pointers[i])
            if new_term != None:
                new_term = self.convert_key_to_int(new_term)
                heapq.heappush(min_heap, (list(new_term.keys())[0], i))
                file_terms[i] = new_term

            # Escribir en disco
            if len(final_terms) >= self.block_size:
                while min_heap:
                    temp_t, temp_i = heapq.heappop(min_heap)
                    if temp_t != doc:
                        heapq.heappush(min_heap, (temp_t, temp_i))
                        break

                    # Actualizar tf_idf
                    final_terms[doc] += file_terms[temp_i][temp_t]
                    file_pointers[temp_i] += 1
                    new_term = self.load_next_term(
                        json_files[temp_i], file_pointers[temp_i]
                    )
                    if new_term != None:
                        new_term = self.convert_key_to_int(new_term)
                        heapq.heappush(min_heap, (list(new_term.keys())[0], temp_i))
                        file_terms[temp_i] = new_term

                # ordenar los postings por doc_id
                final_terms = {
                    doc: tf_idf for doc, tf_idf in sorted(final_terms.items())
                }
                final_terms = {
                    doc_id: np.sqrt(length) for doc_id, length in final_terms.items()
                }

                # Escribir el índice parcial en disco
                # self.write_json_file(dict(final_terms), os.path.join(temp_index_dir, "index_build.json"))
                index_page += 1
                file_name = os.path.join(
                    temp_docs_pages, f"docs_norms_{index_page}.json"
                )
                self.write_file(dict(final_terms), file_name)
                final_terms.clear()

        if final_terms:
            index_page += 1
            file_name = os.path.join(temp_docs_pages, f"docs_norms_{index_page}.json")
            # ordenar los postings por doc_id
            final_terms = {doc: tf_idf for doc, tf_idf in sorted(final_terms.items())}
            final_terms = {
                doc_id: np.sqrt(length) for doc_id, length in final_terms.items()
            }
            self.write_file(dict(final_terms), file_name)

    def convert_key_to_int(self, term_dict):
        return {int(key): value for key, value in term_dict.items()}


# Ejemplo de uso
if __name__ == "__main__":
    dataton = os.path.join(base_path, "spotify_millsongdata_1000.csv")
    index = InvertedIndex(dataton)
    query1 = """Take it easy with me, please  
Touch me gently like a summer evening breeze  
Take your time, make it slow  
Andante, Andante  
Just let the feeling grow  
  
Make your fingers soft and light  
Let your body be the velvet of the night  
Touch my soul, you know how  
Andante, Andante  
Go slowly with me now  
  
I'm your music  
(I am your music and I am your song)  
I'm your song  
(I am your music and I am your song)  
Play me time and time again and make me strong  
(Play me again 'cause you're making me strong)  
Make me sing, make me sound  
(You make me sing and you make me)  
Andante, Andante  
Tread lightly on my ground  
Andante, Andante  
Oh please don't let me down There's a shimmer in your eyes  
Like the feeling of a thousand butterflies  
Please don't talk, go on, play  
Andante, Andante  
And let me float away  
I'm your music  
(I am your music and I am your song)  
I'm your song  
(I am your music and I am your song)  
Play me time and time again and make me strong  
(Play me again 'cause you're making me strong)  
Make me sing, make me sound  
(You make me sing and you make me)  
Andante, Andante  
Tread lightly on my ground  
Andante, Andante  
Oh please don't let me down  
  
Make me sing, make me sound  
(You make me sing and you make me)  
Andante, Andante  
Tread lightly on my ground  
Andante, Andante  
Oh please don't let me down  
Andante, Andante  
Oh please don't let me down
"""
    result = index.retrieve(query1, 5)
    print(result)
