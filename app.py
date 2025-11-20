import streamlit as st
import openai
import json
import os
import tempfile
import numpy as np
import requests
from rembg import remove
from PIL import Image
from moviepy.editor import ImageClip, concatenate_videoclips
from io import BytesIO

# --- 页面基础配置 ---
st.set_page_config(page_title="Mercado Listings Generator", layout="wide")
st.title("🛒 Mercado Libre 全自动Listing生成器")
st.markdown("专注 Mercado 巴西/西语站点：SEO标题 + 6张优化主图 + 视频生成")

# --- 侧边栏：配置 ---
with st.sidebar:
    st.header("⚙️ 设置")
    api_key = st.text_input("输入 OpenAI API Key", type="password")
    target_country = st.selectbox("目标站点", ["巴西 (MLB) - 葡语", "墨西哥 (MLM) - 西语", "阿根廷 (MLA) - 西语"])
    st.info("提示：生成的视频和图片会临时存储，刷新页面后会清空。")

# --- 核心功能类 (封装) ---
class MercadoOptimizer:
    def __init__(self, api_key):
        self.client = openai.OpenAI(api_key=api_key)
        self.target_size = (1200, 1200)

    def generate_text(self, product_info, country):
        lang = "Portuguese" if "巴西" in country else "Spanish"
        prompt = f"""
        你是一个Mercado Libre SEO专家。请将以下中文产品信息转换为{lang}。
        返回JSON格式:
        {{
            "title": "核心大词+品牌+型号+卖点 (60字符以内)",
            "description_html": "HTML格式描述(含<ul><li>卖点)",
            "prompts": {{
                "model": "Photorealistic prompt of a model using this product, commercial photography",
                "lifestyle": "Product in a cozy lifestyle setting, high quality",
                "detail": "Close-up shot showing product texture and quality"
            }}
        }}
        产品信息: {product_info}
        """
        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)

    def remove_bg_and_resize(self, uploaded_file):
        # 读取图片
        image = Image.open(uploaded_file).convert("RGBA")
        # 移除背景
        img_no_bg = remove(image)
        # 创建白底
        new_img = Image.new("RGB", self.target_size, (255, 255, 255))
        # 居中缩放逻辑
        bbox = img_no_bg.getbbox()
        if bbox:
            cropped = img_no_bg.crop(bbox)
            ratio = min(self.target_size[0]*0.85 / cropped.width, self.target_size[1]*0.85 / cropped.height)
            new_size = (int(cropped.width * ratio), int(cropped.height * ratio))
            resized = cropped.resize(new_size, Image.LANCZOS)
            paste_pos = ((self.target_size[0] - new_size[0]) // 2, (self.target_size[1] - new_size[1]) // 2)
            new_img.paste(resized, paste_pos, mask=resized)
        else:
            new_img.paste(img_no_bg, (0,0), mask=img_no_bg)
        
        return new_img

    def generate_ai_image(self, prompt):
        try:
            response = self.client.images.generate(
                model="dall-e-3",
                prompt=f"Studio lighting, 4k, white background style but with context: {prompt}",
                size="1024x1024",
                quality="standard",
                n=1,
            )
            img_url = response.data[0].url
            img_response = requests.get(img_url)
            img = Image.open(BytesIO(img_response.content)).convert("RGB")
            return img.resize(self.target_size, Image.LANCZOS)
        except Exception as e:
            st.error(f"AI绘图出错: {e}")
            return Image.new("RGB", self.target_size, (200, 200, 200))

    def create_video(self, images):
        # 保存临时文件以供MoviePy使用
        temp_files = []
        clips = []
        duration = 10.0 / len(images)
        
        for idx, img in enumerate(images):
            tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            img.save(tfile.name)
            temp_files.append(tfile.name)
            
            # 创建Clip并添加简单缩放效果
            clip = ImageClip(tfile.name).set_duration(duration)
            clip = clip.resize(lambda t: 1 + 0.02 * t).set_position('center').set_fps(24)
            clip = clip.crop(x1=0, y1=0, width=1200, height=1200) # 保持尺寸
            clips.append(clip)

        final_clip = concatenate_videoclips(clips, method="compose")
        output_path = tempfile.mktemp(suffix=".mp4")
        final_clip.write_videofile(output_path, codec='libx264', audio=False, logger=None)
        
        return output_path

# --- 界面输入区 ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. 产品基本信息 (中文)")
    prod_name = st.text_input("产品名称", "真皮商务公文包")
    prod_features = st.text_area("产品卖点/材质/参数", "头层牛皮，防水，可装15寸电脑，复古风格")

with col2:
    st.subheader("2. 原始图片上传")
    st.caption("请上传清晰的实拍图")
    img_front = st.file_uploader("上传：正面图", type=['jpg', 'png', 'jpeg'])
    img_side = st.file_uploader("上传：侧面图", type=['jpg', 'png', 'jpeg'])
    img_back = st.file_uploader("上传：背面图", type=['jpg', 'png', 'jpeg'])

# --- 生成执行区 ---
if st.button("🚀 开始全自动生成", type="primary"):
    if not api_key:
        st.error("请先在左侧边栏输入 OpenAI API Key")
    elif not (img_front and img_side and img_back):
        st.error("请上传全部 3 张基础图片（正、侧、背）")
    else:
        optimizer = MercadoOptimizer(api_key)
        
        # 1. 文本生成
        with st.status("正在分析产品并撰写文案...", expanded=True) as status:
            prod_info = f"Name: {prod_name}, Features: {prod_features}"
            seo_data = optimizer.generate_text(prod_info, target_country)
            st.write("✅ 文案生成完毕")
            
            # 2. 图片处理
            st.write("正在进行AI抠图与白底处理...")
            img_a_front = optimizer.remove_bg_and_resize(img_front)
            img_d_side = optimizer.remove_bg_and_resize(img_side)
            img_e_back = optimizer.remove_bg_and_resize(img_back)
            
            # 3. AI 绘图 (模拟模特/场景)
            st.write("正在调用 DALL-E 3 生成场景图 (耗时较长)...")
            prompts = seo_data['prompts']
            img_b_model = optimizer.generate_ai_image(prompts['model'])
            img_c_detail = optimizer.generate_ai_image(prompts['detail'])
            img_f_scene = optimizer.generate_ai_image(prompts['lifestyle'])
            
            # 组织6张图的顺序
            final_images = [img_a_front, img_b_model, img_c_detail, img_d_side, img_e_back, img_f_scene]
            image_labels = ["A.正面白底", "B.模特展示(AI)", "C.细节特写(AI)", "D.侧面白底", "E.背面白底", "F.场景展示(AI)"]
            
            # 4. 视频合成
            st.write("正在渲染 10s 动态视频...")
            video_path = optimizer.create_video(final_images)
            
            status.update(label="🎉 所有任务完成！", state="complete", expanded=False)

        # --- 结果展示区 ---
        st.divider()
        
        # 展示文案
        st.subheader("📝 优化后的 Listing")
        st.text_input("SEO 标题 (60字符内)", seo_data['title'])
        with st.expander("查看 HTML 描述代码"):
            st.code(seo_data['description_html'], language='html')

        # 展示图片
        st.subheader("🖼️ 优化后的产品图 (1200x1200)")
        img_cols = st.columns(3)
        for i in range(6):
            with img_cols[i % 3]:
                st.image(final_images[i], caption=image_labels[i], use_column_width=True)
                # 提供下载按钮
                buf = BytesIO()
                final_images[i].save(buf, format="JPEG", quality=95)
                st.download_button(f"下载图 {i+1}", buf.getvalue(), f"mercado_img_{i+1}.jpg", "image/jpeg")

        # 展示视频
        st.subheader("🎥 产品展示视频")
        st.video(video_path)
        with open(video_path, "rb") as v:
            st.download_button("下载视频 MP4", v, "mercado_video.mp4")
