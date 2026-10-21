"""Implementação autoral de uma Árvore de Prefixos Compacta (Patricia / Radix Trie)
para indexação e busca por prefixo de códigos Geohash em tempo O(m + k).
"""

from dataclasses import dataclass, field
from typing import Dict, Generic, Iterable, List, Optional, Tuple, TypeVar

T = TypeVar("T")


@dataclass
class RadixTrieNode(Generic[T]):
    """Nó de uma Trie Compacta (Radix Tree).

    Invariantes estruturais:
    - `label` armazena a substring que rotula a aresta de entrada deste nó
      (vazia apenas para a raiz).
    - `children` mapeia o primeiro caractere da aresta de cada filho para o
      respectivo `RadixTrieNode`. Como cada aresta que parte de um mesmo nó
      possui primeiro caractere distinto, a transição em cada nível ocorre em O(1).
    - Todo nó interno com `len(values) == 0` possui pelo menos 2 filhos,
      garantindo a compressão de caminhos unários.
    """

    label: str = ""
    children: Dict[str, "RadixTrieNode[T]"] = field(default_factory=dict)
    values: List[T] = field(default_factory=list)


def _common_prefix_length(a: str, b: str) -> int:
    """Retorna o tamanho do maior prefixo comum entre duas strings."""
    limit = min(len(a), len(b))
    idx = 0
    while idx < limit and a[idx] == b[idx]:
        idx += 1
    return idx


class CompactTrie(Generic[T]):
    """Árvore Trie Compacta para indexação de registros por chave string (Geohash).

    Complexidades de tempo para alfabeto de tamanho constante (Base32 = 32 símbolos):
    - Inserção de chave de comprimento m: O(m)
    - Busca exata de chave de comprimento m: O(m)
    - Busca por prefixo de comprimento m retornando k itens: O(m + k)
      (pois nós internos sem valores têm ramificação >= 2, limitando o número de
      nós visitados na subárvore a no máximo 2 * C, onde C <= k é o número de
      folhas/nós com valores na subárvore).
    """

    def __init__(self) -> None:
        self.root: RadixTrieNode[T] = RadixTrieNode()
        self._size: int = 0

    def __len__(self) -> int:
        return self._size

    def clear(self) -> None:
        """Remove todos os elementos armazenados na Trie."""
        self.root = RadixTrieNode()
        self._size = 0

    def insert(self, key: str, value: T) -> None:
        """Insere um valor associado à chave `key`, comprimindo arestas comuns."""
        if not key:
            raise ValueError("A chave inserida na Trie não pode ser vazia.")

        node = self.root
        remaining = key

        while remaining:
            first_char = remaining[0]
            child = node.children.get(first_char)

            if child is None:
                # Nenhuma aresta compartilha o primeiro caractere: cria folha direta
                new_leaf: RadixTrieNode[T] = RadixTrieNode(
                    label=remaining, values=[value]
                )
                node.children[first_char] = new_leaf
                self._size += 1
                return

            common_len = _common_prefix_length(remaining, child.label)

            if common_len == len(child.label):
                # O rótulo do filho é prefixo completo do restante da chave
                node = child
                remaining = remaining[common_len:]
                continue

            # O rótulo do filho diverge antes do fim: divide a aresta em dois níveis
            common_prefix = child.label[:common_len]
            child_suffix = child.label[common_len:]
            remaining_suffix = remaining[common_len:]

            split_node: RadixTrieNode[T] = RadixTrieNode(label=common_prefix)
            child.label = child_suffix
            split_node.children[child_suffix[0]] = child
            node.children[first_char] = split_node

            if remaining_suffix:
                new_branch: RadixTrieNode[T] = RadixTrieNode(
                    label=remaining_suffix, values=[value]
                )
                split_node.children[remaining_suffix[0]] = new_branch
            else:
                split_node.values.append(value)

            self._size += 1
            return

        node.values.append(value)
        self._size += 1

    def search_exact(self, key: str) -> List[T]:
        """Retorna todos os valores associados exatamente à chave `key` em O(m)."""
        if not key:
            return []

        node = self.root
        remaining = key

        while remaining:
            child = node.children.get(remaining[0])
            if child is None or not remaining.startswith(child.label):
                return []
            remaining = remaining[len(child.label) :]
            node = child

        return list(node.values)

    def _find_prefix_locus(self, prefix: str) -> Optional[RadixTrieNode[T]]:
        """Localiza o nó cuja subárvore contém todas as chaves iniciadas por `prefix`.

        Executa no máximo m comparações de caracteres, portanto O(m).
        """
        node = self.root
        remaining = prefix

        while remaining:
            child = node.children.get(remaining[0])
            if child is None:
                return None

            common_len = _common_prefix_length(remaining, child.label)
            if common_len == len(remaining):
                # O prefixo termina dentro (ou no fim) da aresta de `child`
                return child
            if common_len == len(child.label):
                # A aresta inteira de `child` casa com parte de `prefix`; continua descendo
                remaining = remaining[common_len:]
                node = child
            else:
                # Divergência entre o prefixo buscado e o rótulo da aresta
                return None

        return node

    def search_prefix(self, prefix: str) -> List[T]:
        """Recupera todos os elementos cujas chaves iniciam por `prefix` em O(m + k)."""
        if not prefix:
            return self.all_values()

        locus = self._find_prefix_locus(prefix)
        if locus is None:
            return []

        results: List[T] = []
        stack: List[RadixTrieNode[T]] = [locus]
        while stack:
            current = stack.pop()
            if current.values:
                results.extend(current.values)
            for child in current.children.values():
                stack.append(child)

        return results

    def search_prefixes(self, prefixes: Iterable[str]) -> List[T]:
        """Busca múltiplos prefixos (ex.: célula central + 8 adjacentes) sem duplicar
        prefixos idênticos na consulta.
        """
        aggregated: List[T] = []
        visited_prefixes = set()
        for prefix in prefixes:
            if not prefix or prefix in visited_prefixes:
                continue
            visited_prefixes.add(prefix)
            aggregated.extend(self.search_prefix(prefix))
        return aggregated

    def all_values(self) -> List[T]:
        """Retorna todos os valores armazenados na Trie."""
        results: List[T] = []
        stack: List[RadixTrieNode[T]] = [self.root]
        while stack:
            current = stack.pop()
            if current.values:
                results.extend(current.values)
            for child in current.children.values():
                stack.append(child)
        return results

    def stats(self) -> Tuple[int, int, int]:
        """Retorna (total_itens, total_nos, altura_maxima) para inspeção e testes."""
        node_count = 0
        max_depth = 0
        stack: List[Tuple[RadixTrieNode[T], int]] = [(self.root, 0)]
        while stack:
            node, depth = stack.pop()
            node_count += 1
            if depth > max_depth:
                max_depth = depth
            for child in node.children.values():
                stack.append((child, depth + 1))
        return self._size, node_count, max_depth

