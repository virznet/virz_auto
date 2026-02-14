import os
import random
import time
import requests
import json
import base64
import re
import io
import sys
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from PIL import Image

# 콘솔 출력 시 한글 깨짐 방지 설정
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# ==========================================
# 1. 환경 변수 및 설정
# ==========================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
WP_USERNAME = os.environ.get('WP_USERNAME', '').strip()
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD', '').replace(' ', '').strip()
WP_BASE_URL = "https://virz.net" 

# 테스트 모드: True일 경우 랜덤 대기 없이 즉시 1개 발행 후 종료
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# ==========================================
# 2. 데이터 수집 로직
# ==========================================
def load_external_links():
    file_path = "links.json"
    default_links = [{"title": "virz.net", "url": "https://virz.net"}]
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if data else default_links
        except Exception as e:
            print(f"⚠️ links.json 로드 실패: {e}", flush=True)
            return default_links
    return default_links

class TrendScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
        }

    def get_naver_news_custom(self, url):
        try:
            clean_url = url.strip()
            res = requests.get(clean_url, headers=self.headers, timeout=15)
            res.encoding = res.apparent_encoding if res.apparent_encoding else 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            titles = []
            for selector in [".sa_text_strong", ".rankingnews_list .list_title", ".cluster_text_headline"]:
                items = soup.select(selector)
                if items:
                    titles.extend([t.text.strip() for t in items])
            
            unique_titles = list(dict.fromkeys([t for t in titles if t]))
            return unique_titles[:10]
        except Exception as e:
            print(f"⚠️ 스크래핑 오류 ({url[:30]}...): {e}", flush=True)
            return []

# ==========================================
# 3. 워드프레스 & 이미지 처리
# ==========================================
def get_recent_posts():
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=15&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except Exception as e:
        print(f"최근 포스트 로드 오류: {e}", flush=True)
    return []

def generate_image_process(prompt):
    print(f"🎨 이미지 생성 API 호출 중... (Prompt: {prompt[:30]}...)", flush=True)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    final_prompt = f"Professional photography for: {prompt}. High resolution, 8k, cinematic lighting. Strictly NO TEXT, NO LETTERS, NO WORDS."
    payload = {"instances": [{"prompt": final_prompt}], "parameters": {"sampleCount": 1}}
    try:
        response = requests.post(url, json=payload, timeout=150)
        if response.status_code == 200:
            result = response.json()
            b64_data = result['predictions'][0]['bytesBase64Encoded']
            img_data = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_data))
            if img.mode != 'RGB': img = img.convert('RGB')
            out = io.BytesIO()
            img.save(out, format='JPEG', quality=70, optimize=True)
            print("✨ 이미지 생성 완료!", flush=True)
            return out.getvalue()
        else:
            print(f"❌ 이미지 생성 실패 (HTTP {response.status_code})", flush=True)
    except Exception as e:
        print(f"❌ 이미지 생성 중 오류: {e}", flush=True)
    return None

def upload_to_wp_media(img_data):
    print("📤 워드프레스 미디어 업로드 중...", flush=True)
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=feat_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201:
            media_id = res.json()['id']
            print(f"✅ 미디어 업로드 성공 (ID: {media_id})", flush=True)
            return media_id
    except Exception as e:
        print(f"❌ 미디어 업로드 중 오류: {e}", flush=True)
    return None

# ==========================================
# 4. 스마트 콘텐츠 생성
# ==========================================
def generate_article(keyword, category, internal_posts, user_links):
    print(f"🤖 Gemini API를 통한 콘텐츠 생성 시작... (약 1-2분 소요)", flush=True)
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    selected_int = random.sample(internal_posts, min(len(internal_posts), 2)) if internal_posts else []
    internal_ref = "내 블로그 추천글 (필수 2개 이상 포함):\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in selected_int])
    
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "외부 링크 (필수 2개 이상 포함):\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 매우 상세하고 사람이 직접 작성한 것 같은 품질의 블로그 글을 작성하세요.

[필수 사항: 워드프레스 구텐베르크 블록 형식]
- 모든 콘텐츠는 워드프레스 구텐베르크(Gutenberg) 블록 주석으로 감싸야 합니다.
- 문단: <!-- wp:paragraph --><p>내용</p><!-- /wp:paragraph -->
- 제목(H2): <!-- wp:heading --><h2>제목</h2><!-- /wp:heading -->
- 제목(H3): <!-- wp:heading {{"level":3}} --><h3>제목</h3><!-- /wp:heading -->
- 버튼: <!-- wp:buttons --><div class="wp-block-buttons"><!-- wp:button --><div class="wp-block-button"><a class="wp-block-button__link" href="URL">텍스트</a></div><!-- /wp:button --></div><!-- /wp:buttons -->

[필수 가이드: 휴먼 라이팅 및 가독성]
1. 도입부: 인사말('안녕하세요'), 자기소개 등을 절대 하지 마세요. 본론으로 즉시 시작하세요.
2. 소제목 규칙: 소제목(H2, H3, H4) 작성 시 리스트 순서를 나타내는 숫자(1., 2.), 문자(가., A.), 서수(첫째, 둘째)를 절대 사용하지 마세요.
3. 모바일 최적화: 한 문단은 최대 3줄 이내로 유지하고, 문단 사이 줄바꿈을 과감하게 활용하세요.
4. 금지 문구: 제목이나 본문에 '3000자 분석', 'AI 생성', '프롬프트'와 같은 단어를 절대 노출하지 마세요.

[링크 전략]
- 내부 링크 2개, 외부 링크 2개를 반드시 본문 중간 또는 섹션 하단에 삽입하세요. 
- 버튼 블록(Gutenberg Button) 형식을 적극 활용하세요.

JSON 응답 키: 'title', 'content', 'excerpt', 'tags', 'image_prompt'.
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n카테고리: {category}"
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    for i in range(5):
        try:
            res = requests.post(url, json=payload, timeout=180)
            if res.status_code == 200:
                raw_response = res.json()['candidates'][0]['content']['parts'][0]['text']
                json_str = raw_response.strip()
                if json_str.startswith("```"):
                    json_str = re.sub(r'^`{3}(?:json)?\s*', '', json_str)
                    json_str = re.sub(r'\s*`{3}$', '', json_str)
                json_str = "".join(c for c in json_str if ord(c) >= 32 or c in '\n\r\t')
                print("✅ AI 콘텐츠 생성 완료!", flush=True)
                return json.loads(json_str)
            else:
                print(f"⚠️ API 호출 실패 (HTTP {res.status_code}). 재시도 중... ({i+1}/5)", flush=True)
            time.sleep(2**i)
        except Exception as e:
            print(f"⚠️ 오류 발생: {e}. 재시도 중... ({i+1}/5)", flush=True)
            time.sleep(2**i)
    return None

# ==========================================
# 5. 워드프레스 발행 로직
# ==========================================
def post_article(data, mid):
    print("📢 워드프레스 포스팅 발행 중...", flush=True)
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    tag_ids = []
    tags_raw = data.get('tags', [])
    if tags_raw:
        tag_names = tags_raw if isinstance(tags_raw, list) else [t.strip() for t in str(tags_raw).split(',') if t.strip()]
        for tname in tag_names:
            try:
                r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth, timeout=10)
                tid = None
                if r.status_code == 200:
                    tags_data = r.json()
                    tid = next((t['id'] for t in tags_data if t['name'].lower() == tname.lower()), None)
                if not tid:
                    cr = requests.post(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags", auth=auth, json={"name": tname}, timeout=10)
                    if cr.status_code == 201: tid = cr.json()['id']
                if tid: tag_ids.append(tid)
            except: continue

    payload = {
        "title": data.get('title', '제목 없음'), 
        "content": data.get('content', ''), 
        "excerpt": data.get('excerpt', ''),
        "tags": tag_ids, 
        "featured_media": mid, 
        "status": "publish"
    }
    
    try:
        res = requests.post(url, auth=auth, json=payload, timeout=40)
        if res.status_code == 201:
            print(f"🚀 포스팅 발행 성공! (Link: {res.json().get('link')})", flush=True)
            return True
        else:
            print(f"❌ 발행 실패 (HTTP {res.status_code}): {res.text}", flush=True)
    except Exception as e:
        print(f"❌ 워드프레스 API 발행 오류: {e}", flush=True)
    return False

# ==========================================
# 6. 메인 실행부
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ GEMINI_API_KEY 누락", flush=True); return

    if not IS_TEST:
        start_delay = random.randint(0, 3300) 
        print(f"⏳ {start_delay // 60}분 대기 후 시작합니다...", flush=True)
        time.sleep(start_delay)

    user_links = load_external_links()
    recent_posts = get_recent_posts()
    scraper = TrendScraper()
    
    jobs = [
        ("https://news.naver.com/section/102", "사회"),
        ("https://news.naver.com/section/105", "IT/과학"),
        ("https://news.naver.com/breakingnews/section/103/241", "건강정보"),
        ("https://news.naver.com/breakingnews/section/103/237", "여행/레저"),
        ("https://news.naver.com/breakingnews/section/103/376", "패션/뷰티"),
        ("https://news.naver.com/breakingnews/section/103/242", "공연/전시")
    ]
    
    pool = []
    for url, cat in jobs:
        print(f"📡 {cat} 뉴스 수집 중...", flush=True)
        items = scraper.get_naver_news_custom(url)
        for i in items: pool.append({"kw": i, "cat": cat})
    
    if not pool: 
        print("❌ 수집된 데이터가 없습니다.", flush=True)
        return
    
    targets = random.sample(pool, 1)
    
    for item in targets:
        print(f"📝 대상 키워드: '{item['kw']}'", flush=True)
        data = generate_article(item['kw'], item['cat'], recent_posts, user_links)
        
        if not data:
            print("❌ AI 콘텐츠 생성에 실패하여 이번 턴을 종료합니다.", flush=True)
            continue
        
        mid = None
        if data.get('image_prompt'):
            img_data = generate_image_process(data['image_prompt'])
            if img_data: 
                mid = upload_to_wp_media(img_data)
        
        if post_article(data, mid):
            print(f"🏁 [{item['kw']}] 작업 완료!", flush=True)
        else:
            print("❌ 최종 발행 단계에서 오류가 발생했습니다.", flush=True)

if __name__ == "__main__":
    main()
