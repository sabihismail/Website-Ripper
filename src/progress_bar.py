from progressbar import progressbar


class ProgressBarImpl:
    def __init__(self, total_size: int = 0):
        self.total_size = total_size

        self.progress_bar = progressbar.ProgressBar(maxval=total_size)
        self.progress_bar.start()

    def run(self, block_num, block_size):
        downloaded = block_num * block_size

        if downloaded < self.total_size:
            self.progress_bar.update(downloaded)
        else:
            self.progress_bar.finish()
