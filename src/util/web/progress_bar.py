from typing import Callable

from tqdm import tqdm


class DownloadProgressBar:
    def __init__(self, total_size: int = 0, min_leave_size: int = 1024 * 1024 * 1, on_complete: Callable[[int], None] = None):
        self.total_size = total_size
        self.on_complete = on_complete

        leave = True
        if self.total_size and self.total_size < min_leave_size:
            leave = False

        self.progress_bar = tqdm(total=total_size, unit='iB', unit_scale=True, leave=leave)

    def run(self, byte_count: int) -> bool:
        if self.progress_bar.n < self.total_size:
            self.progress_bar.update(byte_count)

        if self.total_size != 0 and self.progress_bar.n == self.total_size:
            if self.progress_bar.n == 0:
                self.progress_bar.leave = False

            self.progress_bar.close()

            if self.on_complete and self.progress_bar.leave:
                pass  # self.on_complete(self.total_size)

            return False

        return True
