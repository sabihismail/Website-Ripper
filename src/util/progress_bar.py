from tqdm import tqdm


class ProgressBarImpl:
    def __init__(self, total_size: int = 0):
        self.total_size = total_size

        self.progress_bar = tqdm(total=total_size, unit='iB', unit_scale=True)#, leave=False)

    def run(self, block_size):
        if self.progress_bar.n < self.total_size:
            self.progress_bar.update(block_size)

        if self.progress_bar.n == self.total_size:
            self.progress_bar.close()
