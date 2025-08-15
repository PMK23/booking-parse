# parser.py
import os
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from mtranslate import translate
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BookingParser:
    def __init__(self):
        self.output_file = ""
        self.processed_reviews = set()

    def translate_to_russian(self, text):
        try:
            if text and not any('\u0400' <= char <= '\u04FF' for char in text):
                return translate(text, 'ru', 'auto')
            return text
        except Exception as e:
            logger.warning(f"Ошибка перевода: {e}")
            return text

    def get_next_filename(self, output_dir):
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(exist_ok=True)
        counter = 1
        while True:
            filename = output_dir / f"reviews_{counter}.txt"
            if not filename.exists():
                return str(filename)
            counter += 1

    def parse_reviews(self, url: str, output_dir: str):
        """Без прогресса и логов — просто парсинг"""
        try:
            self.output_file = self.get_next_filename(output_dir)
            self.processed_reviews = set()

            options = webdriver.ChromeOptions()
            options.add_argument('--headless')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)

            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)

            driver.get(url)
            time.sleep(2)

            # Принять куки
            try:
                WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="onetrust-accept-btn-handler"]'))
                ).click()
                time.sleep(1)
            except Exception:
                pass

            # Переход на вкладку отзывов
            if "#tab-reviews" not in driver.current_url:
                try:
                    reviews_tab = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, '//a[@href="#tab-reviews"]'))
                    )
                    driver.execute_script("arguments[0].click();", reviews_tab)
                    time.sleep(3)
                except Exception:
                    pass

            # Ждём отзывы
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, '//div[@data-testid="review-card"]'))
                )
            except Exception:
                driver.quit()
                return None, "Не удалось загрузить отзывы"

            total_reviews = 0

            with open(self.output_file, 'w', encoding='utf-8') as f:
                f.write("Отзывы с Booking.com\n")
                f.write(f"URL: {url}\n\n")

            while True:
                # Прокрутка
                last_height = driver.execute_script("return document.body.scrollHeight")
                for _ in range(3):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(0.5)
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        break
                    last_height = new_height

                review_blocks = driver.find_elements(By.XPATH, '//div[@data-testid="review-card"]')

                for review in review_blocks:
                    try:
                        review_id = review.get_attribute('id') or str(hash(review.text[:100]))
                        if review_id in self.processed_reviews:
                            continue
                        self.processed_reviews.add(review_id)
                        total_reviews += 1

                        # Извлечение данных
                        title = ""
                        try:
                            title_el = review.find_element(By.XPATH, './/h4[@data-testid="review-title"]')
                            title = self.translate_to_russian(title_el.text.strip())
                        except NoSuchElementException:
                            pass

                        positive = ""
                        try:
                            pos_el = review.find_element(By.XPATH, './/div[@data-testid="review-positive-text"]')
                            positive = self.translate_to_russian(pos_el.text.strip())
                        except NoSuchElementException:
                            pass

                        negative = ""
                        try:
                            neg_el = review.find_element(By.XPATH, './/div[@data-testid="review-negative-text"]')
                            negative = self.translate_to_russian(neg_el.text.strip())
                        except NoSuchElementException:
                            pass

                        date = "Дата не указана"
                        try:
                            date_el = review.find_element(By.XPATH, './/span[@data-testid="review-date"]')
                            date = date_el.text.strip().replace("Дата отзыва:", "").strip()
                        except NoSuchElementException:
                            pass

                        name = "Аноним"
                        try:
                            name_el = review.find_element(By.XPATH, './/div[contains(@class, "b08850ce41")]')
                            name = name_el.text.strip()
                        except NoSuchElementException:
                            pass

                        rating = ""
                        try:
                            rating = review.find_element(By.XPATH, './/div[@aria-hidden="true"]').get_attribute('aria-label')
                        except NoSuchElementException:
                            pass

                        review_type = "mixed" if positive and negative else "positive" if positive else "negative" if negative else "neutral"

                        with open(self.output_file, 'a', encoding='utf-8') as f:
                            f.write(f"Review_number: id{total_reviews}\n")
                            f.write(f"Review_date: {date}\n")
                            f.write(f"Review_owner: {name}\n")
                            f.write(f"Review_type: {review_type}\n")
                            if title: f.write(f"Review_title: {title}\n")
                            if positive: f.write(f"Positive feedback: {positive}\n")
                            if negative: f.write(f"Negative feedback: {negative}\n")
                            if rating: f.write(f"Review_rating: {rating}\n")
                            f.write("\n")

                    except Exception as e:
                        logger.error(f"Ошибка отзыва: {e}")
                        continue

                # Проверка следующей страницы
                try:
                    next_btn = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, '//button[@aria-label="Следующая страница"]'))
                    )
                    if "disabled" in next_btn.get_attribute("class"):
                        break
                    driver.execute_script("arguments[0].click();", next_btn)
                    time.sleep(3)
                except Exception:
                    break

            driver.quit()
            return self.output_file, f"Готово! Сохранено {total_reviews} отзывов в {self.output_file}"

        except Exception as e:
            logger.error(f"Ошибка парсинга: {e}")
            return None, f"Ошибка: {str(e)}"