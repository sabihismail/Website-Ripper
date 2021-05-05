from collections import MutableSet, OrderedDict
from enum import Enum
from queue import Queue


# Retrieved and modified from https://stackoverflow.com/a/1653978
class OrderedSet(OrderedDict, MutableSet):
    def pop_first(self):
        key, _ = self.popitem(last=False)
        return key

    def pop_last(self):
        key, _ = self.popitem(last=False)
        return key

    def update(self, *args, **kwargs):
        if kwargs:
            raise TypeError("update() takes no keyword arguments")

        for s in args:
            for e in s:
                self.add(e)

    def add(self, elem):
        self[elem] = None

    def discard(self, elem):
        self.pop(elem, None)

    def __le__(self, other):
        return all(e in other for e in self)

    def __lt__(self, other):
        return self <= other and self != other

    def __ge__(self, other):
        return all(e in self for e in other)

    def __gt__(self, other):
        return self >= other and self != other

    def __repr__(self):
        return 'OrderedSet([%s])' % (', '.join(map(repr, self.keys())))

    def __str__(self):
        return '{%s}' % (', '.join(map(repr, self.keys())))

    difference = property(lambda self: self.__sub__)
    difference_update = property(lambda self: self.__isub__)
    intersection = property(lambda self: self.__and__)
    intersection_update = property(lambda self: self.__iand__)
    issubset = property(lambda self: self.__le__)
    issuperset = property(lambda self: self.__ge__)
    symmetric_difference = property(lambda self: self.__xor__)
    symmetric_difference_update = property(lambda self: self.__ixor__)
    union = property(lambda self: self.__or__)


class QueueType(Enum):
    FIFO = 'FIFO',
    LIFO = 'LIFO'


class OrderedSetQueue(Queue):
    def __init__(self, maxsize: int = 0, queue_type: QueueType = QueueType.FIFO):
        super().__init__(maxsize)

        self.queue_type = queue_type

    def _init(self, maxsize: int):
        self.queue: OrderedSet = OrderedSet()

    def _put(self, item):
        self.queue.add(item)

    def _get(self):
        if self.queue_type == QueueType.FIFO:
            return self.queue.pop_first()
        else:
            return self.queue.pop_last()

    def _qsize(self):
        return len(self.queue)

    def dequeue(self):
        return self.get()

    def enqueue(self, item):
        self.put(item)

    def enqueue_list(self, lst):
        for elem in lst:
            self.put(elem)

    def __repr__(self):
        return self.queue.__repr__()
