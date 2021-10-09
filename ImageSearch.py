import re
import asyncio
import copy
from functools import partial
from io import BytesIO
from tkinter import *
from tkinter import messagebox
import sys

import aiohttp
from PIL import Image, ImageTk
from requests.exceptions import ConnectionError


class ScrolledFrame(Frame):
    """Implementation of the scrollable frame widget.
    Copyright (c) 2018 Benjamin Johnson
    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:
    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.
    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

    Scrollable Frame widget.
    Use display_widget() to set the interior widget. For example,
    to display a Label with the text "Hello, world!", you can say:
        sf = ScrolledFrame(self)
        sf.pack()
        sf.display_widget(Label, text="Hello, world!")
    The constructor accepts the usual Tkinter keyword arguments, plus
    a handful of its own:
      scrollbars (str; default: "both")
        Which scrollbars to provide.
        Must be one of "vertical", "horizontal," "both", or "neither".
      use_ttk (bool; default: False)
        Whether to use ttk widgets if available.
        The default is to use standard Tk widgets. This setting has
        no effect if ttk is not available on your system.
    """
    def __init__(self, master=None, **kw):
        """Return a new scrollable frame widget."""

        Frame.__init__(self, master)

        # Hold these names for the interior widget
        self._interior = None
        self._interior_id = None

        # Whether to fit the interior widget's width to the canvas
        self._fit_width = False

        # Which scrollbars to provide
        if "scrollbars" in kw:
            scrollbars = kw["scrollbars"]
            del kw["scrollbars"]

            if not scrollbars:
                scrollbars = self._DEFAULT_SCROLLBARS
            elif not scrollbars in self._VALID_SCROLLBARS:
                raise ValueError("scrollbars parameter must be one of "
                                 "'vertical', 'horizontal', 'both', or "
                                 "'neither'")
        else:
            scrollbars = self._DEFAULT_SCROLLBARS

        # Default to a 1px sunken border
        if not "borderwidth" in kw:
            kw["borderwidth"] = 1
        if not "relief" in kw:
            kw["relief"] = "sunken"

        # Set up the grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Canvas to hold the interior widget
        c = self._canvas = Canvas(self,
                                     borderwidth=0,
                                     highlightthickness=0,
                                     takefocus=0)

        # Enable scrolling when the canvas has the focus
        self.bind_arrow_keys(c)
        self.bind_scroll_wheel(c)

        # Call _resize_interior() when the canvas widget is updated
        c.bind("<Configure>", self._resize_interior)

        # Scrollbars
        xs = self._x_scrollbar = Scrollbar(self,
                                           orient="horizontal",
                                           command=c.xview)
        ys = self._y_scrollbar = Scrollbar(self,
                                           orient="vertical",
                                           command=c.yview)
        c.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)

        # Lay out our widgets
        c.grid(row=0, column=0, sticky="nsew")
        if scrollbars == "vertical" or scrollbars == "both":
            ys.grid(row=0, column=1, sticky="ns")
        if scrollbars == "horizontal" or scrollbars == "both":
            xs.grid(row=1, column=0, sticky="we")

        # Forward these to the canvas widget
        self.bind = c.bind
        self.focus_set = c.focus_set
        self.unbind = c.unbind
        self.xview = c.xview
        self.xview_moveto = c.xview_moveto
        self.yview = c.yview
        self.yview_moveto = c.yview_moveto

        # Process our remaining configuration options
        self.configure(**kw)

    def __setitem__(self, key, value):
        """Configure resources of a widget."""

        if key in self._CANVAS_KEYS:
            # Forward these to the canvas widget
            self._canvas.configure(**{key: value})

        else:
            # Handle everything else normally
            Frame.configure(self, **{key: value})

    # ------------------------------------------------------------------------

    def bind_arrow_keys(self, widget):
        """Bind the specified widget's arrow key events to the canvas."""

        widget.bind("<Up>",
                    lambda event: self._canvas.yview_scroll(-1, "units"))

        widget.bind("<Down>",
                    lambda event: self._canvas.yview_scroll(1, "units"))

        widget.bind("<Left>",
                    lambda event: self._canvas.xview_scroll(-1, "units"))

        widget.bind("<Right>",
                    lambda event: self._canvas.xview_scroll(1, "units"))

    def bind_scroll_wheel(self, widget):
        """Bind the specified widget's mouse scroll event to the canvas."""

        widget.bind("<MouseWheel>", self._scroll_canvas)
        widget.bind("<Button-4>", self._scroll_canvas)
        widget.bind("<Button-5>", self._scroll_canvas)

    def cget(self, key):
        """Return the resource value for a KEY given as string."""

        if key in self._CANVAS_KEYS:
            return self._canvas.cget(key)

        else:
            return Frame.cget(self, key)

    # Also override this alias for cget()
    __getitem__ = cget

    def configure(self, cnf=None, **kw):
        """Configure resources of a widget."""

        # This is overridden so we can use our custom __setitem__()
        # to pass certain options directly to the canvas.
        if cnf:
            for key in cnf:
                self[key] = cnf[key]

        for key in kw:
            self[key] = kw[key]

    # Also override this alias for configure()
    config = configure

    def display_widget(self, widget_class, fit_width=False, **kw):
        """Create and display a new widget.
        If fit_width == True, the interior widget will be stretched as
        needed to fit the width of the frame.
        Keyword arguments are passed to the widget_class constructor.
        Returns the new widget.
        """

        # Blank the canvas
        self.erase()

        # Set width fitting
        self._fit_width = fit_width

        # Set the new interior widget
        self._interior = widget_class(self._canvas, **kw)

        # Add the interior widget to the canvas, and save its widget ID
        # for use in _resize_interior()
        self._interior_id = self._canvas.create_window(0, 0,
                                                       anchor="nw",
                                                       window=self._interior)

        # Call _update_scroll_region() when the interior widget is resized
        self._interior.bind("<Configure>", self._update_scroll_region)

        # Fit the interior widget to the canvas if requested
        # We don't need to check fit_width here since _resize_interior()
        # already does.
        self._resize_interior()

        # Scroll to the top-left corner of the canvas
        self.scroll_to_top()

        return self._interior

    def erase(self):
        """Erase the displayed widget."""

        # Clear the canvas
        self._canvas.delete("all")

        # Delete the interior widget
        del self._interior
        del self._interior_id

        # Save these names
        self._interior = None
        self._interior_id = None

        # Reset width fitting
        self._fit_width = False

    def scroll_to_top(self):
        """Scroll to the top-left corner of the canvas."""

        self._canvas.xview_moveto(0)
        self._canvas.yview_moveto(0)

    # ------------------------------------------------------------------------

    def _resize_interior(self, event=None):
        """Resize the interior widget to fit the canvas."""

        if self._fit_width and self._interior_id:
            # The current width of the canvas
            canvas_width = self._canvas.winfo_width()

            # The interior widget's requested width
            requested_width = self._interior.winfo_reqwidth()

            if requested_width != canvas_width:
                # Resize the interior widget
                new_width = max(canvas_width, requested_width)
                self._canvas.itemconfigure(self._interior_id, width=new_width)

    def _scroll_canvas(self, event):
        """Scroll the canvas."""

        c = self._canvas

        if sys.platform.startswith("darwin"):
            # macOS
            c.yview_scroll(-1 * event.delta, "units")

        elif event.num == 4:
            # Unix - scroll up
            c.yview_scroll(-1, "units")

        elif event.num == 5:
            # Unix - scroll down
            c.yview_scroll(1, "units")

        else:
            # Windows
            c.yview_scroll(-1 * (event.delta // 120), "units")

    def _update_scroll_region(self, event):
        """Update the scroll region when the interior widget is resized."""

        # The interior widget's requested width and height
        req_width = self._interior.winfo_reqwidth()
        req_height = self._interior.winfo_reqheight()

        # Set the scroll region to fit the interior widget
        self._canvas.configure(scrollregion=(0, 0, req_width, req_height))

    # ------------------------------------------------------------------------

    # Keys for configure() to forward to the canvas widget
    _CANVAS_KEYS = "width", "height", "takefocus"

    # Scrollbar-related configuration
    _DEFAULT_SCROLLBARS = "both"
    _VALID_SCROLLBARS = "vertical", "horizontal", "both", "neither"


class ImageFinder:
    def __init__(self, master, search_term, saving_dir, async_loop, **kwargs):
        """
        :param master:
        :param search_term:
        :param saving_dir:
        :param url_scrapper: function that returns image urls by given query
        :param init_urls: custom urls to be displayed
        :param async_loop: asyncio Event Loop
        :param headers: request headers
        :param timeout: request timeout
        :param show_image_width: maximum image display width
        :param show_image_height: maximum image display height
        :param saving_image_width: maximum image saving width
        :param saving_image_height: maximum image saving height
        :param image_saving_name_pattern: modifies saving name. example: "this_image_{}"
        :param n_images_in_row:
        :param n_rows:
        :param button_padx:
        :param button_pady:
        :param window_width_limit: maximum width of the window
        :param window_height_limit: maximum height of the window
        :param window_bg: window background color
        """
        self.button_bg = "#FFFFFF"
        self.activebackground = "#FFFFFF"
        self.saving_dir = saving_dir

        self.async_loop = async_loop
        self.headers = kwargs.get("headers")
        self.timeout = kwargs.get("timeout", 1)
        self.session = None

        if not search_term:
            messagebox.showerror(message="Empty search query")
            return

        self.search_term = search_term
        self.current_row_index = 0
        self.n_images_in_row = kwargs.get("n_images_in_row", 3)
        self.n_rows = kwargs.get("n_rows", 1)
        self.img_urls = kwargs.get("init_urls", [])

        url_scrapper = kwargs.get("url_scrapper")
        if url_scrapper is not None:
            try:
                self.img_urls.extend(url_scrapper(search_term))
            except ConnectionError:
                messagebox.showerror(message="Check your internet connection")
                return

        self.show_more_gen = self.show_more()
        self.button_padx = kwargs.get("button_padx", 10)
        self.button_pady = kwargs.get("button_pady", 10)

        self.optimal_visual_width = kwargs.get("show_image_width")
        self.optimal_visual_height = kwargs.get("show_image_height")

        self.image_saving_name_pattern = kwargs.get("image_saving_name_pattern", "{}")

        self.optimal_result_width = kwargs.get("saving_image_width")
        self.optimal_result_height = kwargs.get("saving_image_height")
        self.main_window = Toplevel(master=master)
        self.main_window.title("Image search")

        self.sf = ScrolledFrame(self.main_window, scrollbars="both")
        self.sf.pack(side="top", expand=1, fill="both")
        self.sf.bind_scroll_wheel(self.main_window)
        self.inner_frame = self.sf.display_widget(partial(Frame, bg=kwargs.get("window_bg", "#FFFFFF")))

        window_width_limit = kwargs.get("window_width_limit")
        window_height_limit = kwargs.get("window_height_limit")
        self.window_width_limit = window_width_limit if window_width_limit is not None else \
            master.winfo_screenwidth() - self.sf._y_scrollbar.winfo_width()
        self.window_height_limit = window_height_limit if window_height_limit is not None else \
            master.winfo_screenheight() - self.sf._x_scrollbar.winfo_height() - 100

        self.saving_images = []
        self.saving_images_names = []
        self.downloading_indexes = []
        self.button_list = []

        self.main_window.grab_set()
        self.main_window.resizable(0, 0)
        self.main_window.protocol("WM_DELETE_WINDOW", self.close_image_search)
        self.main_window.bind("<Escape>", lambda event: self.main_window.destroy())
        self.main_window.bind("<Return>", lambda event: self.close_image_search())

    async def init_session(self):
        connector = aiohttp.TCPConnector(limit=self.n_images_in_row * self.n_rows)
        self.session = aiohttp.ClientSession(headers=self.headers, connector=connector)

    def geometry(self, new_geometry):
        self.main_window.geometry(new_geometry)
        self.main_window.update()

    def start(self):
        if hasattr(self, "show_more_gen"):  # checks whether current instance has images to fetch
            self.async_loop.run_until_complete(self.init_session())
            next(self.show_more_gen)

    def close_image_search(self):
        self.async_loop.run_until_complete(self.session.close())
        for index in self.downloading_indexes:
            saving_image = self.prepare_image(self.saving_images[index],
                                              width=self.optimal_result_width, height=self.optimal_result_height)
            saving_name = self.image_saving_name_pattern.format(self.saving_images_names[index])
            saving_image.save(f"{self.saving_dir}/{saving_name}.png")
        self.main_window.destroy()
    
    @staticmethod
    def prepare_image(img, width: int = None, height: int = None):
        processed_img = copy.copy(img)
        if width is not None and processed_img.width > width:
            k_width = width / processed_img.width
            processed_img = processed_img.resize((width, int(processed_img.height * k_width)),
                                                 Image.ANTIALIAS)

        if height is not None and processed_img.height > height:
            k_height = height / processed_img.height
            processed_img = processed_img.resize((int(processed_img.width * k_height), height),
                                                 Image.ANTIALIAS)
        return processed_img

    def get_button_image(self, img):
        img_show = self.prepare_image(img, width=self.optimal_visual_width, height=self.optimal_visual_height)
        button_img = ImageTk.PhotoImage(img_show)
        return button_img

    async def fetch(self, url):
        """
        fetches image from web
        :param url: image url
        :return: status, button_img, img, hash_url (name for saving)
        """
        try:
            async with self.session.get(url, timeout=self.timeout) as response:
                content = await response.content.read()
                img = Image.open(BytesIO(content))
                button_img = self.get_button_image(img)
                hash_url = hash(url)
                return True, button_img, img, hash_url
        except Exception:
            return False, None, None, None

    def get_images(self, img_urls):
        image_fetch_tasks = []
        for url in img_urls:
            image_fetch_tasks.append(self.fetch(url))
        return image_fetch_tasks

    async def process_batch(self, index, step, request_depth=0):
        button_images_batch = []
        image_urls_batch = []
        to_fetch_button_images_batch = []
        to_fetch_image_urls_batch = []
        url_batch = self.img_urls[index:index + step]
        index += step
        n_images_to_fetch = 0

        image_data_batch = self.get_images(url_batch)

        for check_index, image_future in enumerate(asyncio.as_completed(image_data_batch)):
            status, button_img, img, hash_url = await image_future
            if status:
                button_images_batch.append(button_img)
                image_urls_batch.append(self.img_urls[check_index])
                self.saving_images.append(img)
                self.saving_images_names.append(hash_url)
            else:
                n_images_to_fetch += 1
        if request_depth < 10 and n_images_to_fetch:
            index, to_fetch_button_images_batch, to_fetch_image_urls_batch = await self.process_batch(index,
                                                                                                      n_images_to_fetch,
                                                                                                      request_depth + 1)

        return index, button_images_batch + to_fetch_button_images_batch, image_urls_batch + to_fetch_image_urls_batch

    def get_batch_cash(self, step):
        i = 0
        while i < len(self.img_urls):
            i, button_images_batch, image_urls_batch = self.async_loop.run_until_complete(self.process_batch(i, step))
            yield button_images_batch, image_urls_batch

    def choose_pic(self, url_img_url, button):
        if not button.is_picked:
            button["bg"] = "#FF0000"
            self.downloading_indexes.append(button.image_index)
        else:
            button["bg"] = self.button_bg
            self.downloading_indexes.remove(button.image_index)
        button.is_picked = not button.is_picked

    def show_images(self, cashed_image_batch, urls, start_row=0):
        for j in range(len(cashed_image_batch)):
            b = Button(master=self.inner_frame, image=cashed_image_batch[j],
                       bg=self.button_bg, activebackground=self.activebackground)
            b.image = cashed_image_batch[j]
            b.is_picked = False
            b.image_index = self.n_images_in_row * start_row + j
            b["command"] = lambda x=urls[j], y=b: self.choose_pic(x, y)
            b.grid(row=start_row + (j // self.n_images_in_row + 1), column=j % self.n_images_in_row,
                   padx=self.button_padx, pady=self.button_pady, sticky="news")
            self.button_list.append(b)

        # self.button_list[min(len(self.button_list) - 1, start_row * self.n_images_in_row)].focus_set()
        # for j in range(len(self.button_list)):
        #     self.button_list[j].lift()
        #     self.button_list[j].bind("<Tab>", focus_next_window)
        #     self.button_list[j].bind("<Shift-Tab>", focus_prev_window)
        # self.show_more_button.lift()

    def show_more(self):
        more_colspan = self.n_images_in_row // 2
        if self.n_images_in_row % 2 == 1:
            more_colspan += 1

        self.show_more_button = Button(master=self.inner_frame, text="Show more",
                                       command=lambda x=self.show_more_gen: next(x))
        self.add_images = Button(master=self.inner_frame, text="Download",
                                 command=lambda: self.close_image_search())

        cashed_generator = self.get_batch_cash(self.n_rows * self.n_images_in_row)
        try:
            for cashed_batch, urls in cashed_generator:
                self.show_images(cashed_batch, urls, self.current_row_index)
                self.current_row_index += self.n_rows
                self.show_more_button.grid(row=self.current_row_index + 1, column=0,
                                           columnspan=more_colspan, sticky="nwes")
                self.add_images.grid(row=self.current_row_index + 1, column=more_colspan,
                                     columnspan=more_colspan, sticky="nwes")

                self.inner_frame.update()
                current_frame_width = self.inner_frame.winfo_width()
                current_frame_height = self.inner_frame.winfo_height()
                self.sf.config(width=min(self.window_width_limit, current_frame_width),
                               height=min(self.window_height_limit, current_frame_height))
                yield
            self.show_more_button["state"] = DISABLED
            yield
        except StopIteration:
            self.show_more_button["state"] = DISABLED


def start_image_search(word, master, saving_dir, **kwargs):
    async_loop = asyncio.get_event_loop()
    image_finder = ImageFinder(search_term=word, master=master, saving_dir=saving_dir, async_loop=async_loop, **kwargs)
    print(len(image_finder.img_urls))
    image_finder.geometry("+0+0")
    image_finder.start()


if __name__ == "__main__":
    test_urls = ["https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"]

    def test_scrapper(search_term: None) -> list:
        return test_urls

    root = Tk()
    root.withdraw()
    root.after(0, start_image_search("test", root, "./", url_scrapper=test_scrapper, show_image_width=300))
    root.after(0, start_image_search("test", root, "./", init_urls=test_urls, show_image_width=300))
    root.mainloop()
