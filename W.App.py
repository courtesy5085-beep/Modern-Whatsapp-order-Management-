import streamlit as st
import pandas as pd
import re
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from streamlit_option_menu import option_menu
from streamlit_extras.metric_cards import style_metric_cards
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
import streamlit_authenticator as stauth
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO
import requests

st.set_page_config(
    page_title="OrderFlow Pro",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Database Setup ---
engine = create_engine("sqlite:///orders.db", connect_args={"check_same_thread": False})
Base = declarative_base()
Session = sessionmaker(bind=engine)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    name = Column(String)
    password = Column(String)
    orders = relationship("Order", back_populates="user")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    order_id = Column(String)
    customer = Column(String)
    phone = Column(String)
    product = Column(String)
    qty = Column(Integer)
    price = Column(Float)
    status = Column(String)
    order_date = Column(DateTime)
    notes = Column(Text)
    user = relationship("User", back_populates="orders")

Base.metadata.create_all(engine)

STATUS_COLORS = {
    "Pending": "#FFA500",
    "Packed": "#1E90FF",
    "Shipped": "#9370DB",
    "Delivered": "#32CD32",
    "Cancelled": "#FF6347"
}

STATUS_ICONS = {
    "Pending": "⏳",
    "Packed": "📦",
    "Shipped": "🚚",
    "Delivered": "✅",
    "Cancelled": "❌"
}

# --- Auth Setup ---
def load_credentials():
    session = Session()
    users = session.query(User).all()
    session.close()

    credentials = {"usernames": {}}
    for u in users:
        credentials["usernames"][u.username] = {
            "name": u.name,
            "password": u.password
        }
    return credentials

credentials = load_credentials()
authenticator = stauth.Authenticate(
    credentials, "orderflow_cookie", "orderflow_key", cookie_expiry_days=30
)

# --- Helper Functions ---
def generate_pdf_invoice(order):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, height - 50, "OrderFlow Pro")

    c.setFont("Helvetica", 12)
    c.drawString(50, height - 90, f"Invoice: {order.order_id}")
    c.drawString(50, height - 110, f"Date: {order.order_date.strftime('%d %b %Y %I:%M %p')}")

    c.drawString(50, height - 150, f"Customer: {order.customer}")
    c.drawString(50, height - 170, f"Phone: {order.phone}")

    c.line(50, height - 190, width - 50, height - 190)

    c.drawString(50, height - 210, "Product")
    c.drawString(300, height - 210, "Qty")
    c.drawString(400, height - 210, "Price")
    c.drawString(500, height - 210, "Total")

    c.drawString(50, height - 230, order.product)
    c.drawString(300, height - 230, str(order.qty))
    c.drawString(400, height - 230, f"PKR {order.price:.0f}")
    c.drawString(500, height - 230, f"PKR {order.qty * order.price:.0f}")

    c.line(50, height - 250, width - 50, height - 250)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(400, height - 270, f"Total: PKR {order.qty * order.price:.0f}")

    c.save()
    buffer.seek(0)
    return buffer

def send_whatsapp_message(phone, message):
    """
    WhatsApp Business API integration
    Set WHATSAPP_TOKEN and WHATSAPP_PHONE_ID in environment variables
    """
    token = st.secrets.get("WHATSAPP_TOKEN", "")
    phone_id = st.secrets.get("WHATSAPP_PHONE_ID", "")

    if not token or not phone_id:
        return False, "WhatsApp API not configured"

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }

    try:
        r = requests.post(url, json=payload, headers=headers)
        return r.status_code == 200, r.json()
    except Exception as e:
        return False, str(e)

def parse_whatsapp_message(text):
    patterns = {
        "name": r"(?:name|naam|customer)[:\-]\s*([A-Za-z\s]+)",
        "phone": r"(?:phone|contact|#|mobile)[:\-]\s*([+\d\s\-\(\)]{10,})",
        "product": r"(?:product|item|order)[:\-]\s*([^\n]+)",
        "qty": r"(?:qty|quantity|qnt|x)[:\-]\s*(\d+)",
        "price": r"(?:price|amount|rs|pkr|total)[:\-]\s*([\d,]+)"
    }
    data = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            data[key] = match.group(1).strip()
    numbers = re.findall(r'\d+', text)
    if "qty" not in data and numbers:
        data["qty"] = numbers[0]
    if "price" not in data and len(numbers) > 1:
        data["price"] = numbers[-1]
    return data

def load_orders(user_id):
    session = Session()
    df = pd.read_sql(session.query(Order).filter(Order.user_id == user_id).statement, session.bind)
    session.close()
    return df

def add_order(user_id, customer, phone, product, qty, price, notes=""):
    session = Session()
    count = session.query(Order).filter(Order.user_id == user_id).count()
    new_order = Order(
        user_id=user_id,
        order_id=f"ORD{count+1:04d}",
        customer=customer,
        phone=phone,
        product=product,
        qty=int(qty),
        price=float(price),
        status="Pending",
        order_date=datetime.now(),
        notes=notes
    )
    session.add(new_order)
    session.commit()
    session.close()

def update_orders(df, user_id):
    session = Session()
    for _, row in df.iterrows():
        order = session.query(Order).filter_by(id=row['id'], user_id=user_id).first()
        if order:
            order.status = row['status']
            order.qty = int(row['qty'])
            order.price = float(row['price'])
            order.customer = row['customer']
            order.product = row['product']
    session.commit()
    session.close()

# --- Auth UI ---
name, authentication_status, username = authenticator.login("Login", "main")

if authentication_status == False:
    st.error("Username/password is incorrect")
elif authentication_status == None:
    st.warning("Please enter your username and password")

    st.markdown("### Don't have an account?")
    with st.expander("Sign Up"):
        with st.form("signup"):
            new_name = st.text_input("Name")
            new_username = st.text_input("Username")
            new_password = st.text_input("Password", type="password")
            if st.form_submit_button("Create Account"):
                if new_username and new_password and new_name:
                    session = Session()
                    if session.query(User).filter_by(username=new_username).first():
                        st.error("Username already exists")
                    else:
                        hashed_pw = stauth.Hasher([new_password]).generate()[0]
                        user = User(username=new_username, name=new_name, password=hashed_pw)
                        session.add(user)
                        session.commit()
                        st.success("Account created! Please login.")
                    session.close()
else:
    # --- Main App ---
    session = Session()
    current_user = session.query(User).filter_by(username=username).first()
    session.close()

    authenticator.logout("Logout", "sidebar")
    st.sidebar.write(f"Welcome, **{current_user.name}**")

    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');
        html, body, [class*="css"] {font-family: 'Poppins', sans-serif;}
      .main-header {
            font-size: 2.5rem; font-weight: 700;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem;
        }
      .order-card {
            padding: 1.5rem; border-radius: 16px;
            background: rgba(102, 126, 234, 0.1);
            border: 1px solid rgba(102, 126, 234, 0.2);
            margin-bottom: 1rem;
        }
    </style>
    """, unsafe_allow_html=True)

    with st.sidebar:
        selected = option_menu(
            menu_title=None,
            options=["Dashboard", "Add Order", "Manage Orders", "Analytics", "Export"],
            icons=["speedometer2", "plus-circle", "list-check", "bar-chart", "download"],
            default_index=0,
            styles={
                "container": {"padding": "0!important", "background-color": "transparent"},
                "icon": {"color": "#667eea", "font-size": "18px"},
                "nav-link": {"font-size": "16px", "text-align": "left", "margin": "5px 0", "border-radius": "12px"},
                "nav-link-selected": {"background": "linear-gradient(90deg, #667eea 0%, #764ba2 100%)"},
            }
        )

    df = load_orders(current_user.id)

    # Dashboard
    if selected == "Dashboard":
        st.markdown('<div class="main-header">Dashboard</div>', unsafe_allow_html=True)
        if df.empty:
            st.info("👋 Add your first order to see analytics here.")
        else:
            df["revenue"] = df["price"] * df["qty"]
            today = datetime.now().date()
            today_orders = df[df["order_date"].dt.date == today]

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Orders", len(df), delta=f"+{len(today_orders)} today")
            col2.metric("Revenue", f"PKR {df['revenue'].sum():,.0f}")
            col3.metric("Avg Order Value", f"PKR {df['revenue'].mean():,.0f}")
            col4.metric("Delivered Rate", f"{len(df[df['status']=='Delivered'])/len(df)*100:.1f}%")
            style_metric_cards(border_radius=16)

    # Add Order
    elif selected == "Add Order":
        st.markdown('<div class="main-header">Add New Order</div>', unsafe_allow_html=True)
        col1, col2 = st.columns([2, 1])

        with col1:
            msg = st.text_area("Paste WhatsApp Message", height=120)
            if st.button("✨ Auto-Fill Fields"):
                parsed = parse_whatsapp_message(msg)
                st.session_state.parsed_data = parsed
                st.success("Fields extracted!")

            parsed_data = st.session_state.get("parsed_data", {})

            with st.form("order_form", clear_on_submit=True):
                customer = st.text_input("Customer Name", value=parsed_data.get("name", ""))
                phone = st.text_input("Phone", value=parsed_data.get("phone", ""))
                product = st.text_input("Product", value=parsed_data.get("product", ""))
                col_c, col_d = st.columns(2)
                qty = col_c.number_input("Quantity", min_value=1, value=int(parsed_data.get("qty", 1)))
                price = col_d.number_input("Price (PKR)", min_value=0.0, value=float(parsed_data.get("price", 0)))
                notes = st.text_area("Notes", height=80)

                if st.form_submit_button("➕ Create Order", type="primary"):
                    if customer and phone and product:
                        add_order(current_user.id, customer, phone, product, qty, price, notes)
                        st.balloons()
                        st.success(f"Order created for {customer}!")
                        st.session_state.parsed_data = {}
                    else:
                        st.error("Please fill required fields")

    # Manage Orders
    elif selected == "Manage Orders":
        st.markdown('<div class="main-header">Manage Orders</div>', unsafe_allow_html=True)
        if df.empty:
            st.warning("No orders yet.")
        else:
            filtered_df = df.copy()
            gb = GridOptionsBuilder.from_dataframe(filtered_df)
            gb.configure_column("status", editable=True, cellEditor="agSelectCellEditor",
                               cellEditorParams={'values': list(STATUS_COLORS.keys())})
            gb.configure_column("id", hide=True)
            gb.configure_pagination(paginationAutoPageSize=True)

            grid_response = AgGrid(
                filtered_df,
                gridOptions=gb.build(),
                update_mode=GridUpdateMode.MODEL_CHANGED,
                theme="streamlit",
                height=400
            )

            col1, col2 = st.columns(2)
            if col1.button("💾 Save Changes", type="primary"):
                update_orders(grid_response['data'], current_user.id)
                st.success("Changes saved!")
                st.rerun()

            st.markdown("### Download Invoice")
            selected_order_id = col2.selectbox("Select Order", df["order_id"].tolist())
            if st.button("📄 Generate PDF"):
                session = Session()
                order = session.query(Order).filter_by(order_id=selected_order_id, user_id=current_user.id).first()
                pdf = generate_pdf_invoice(order)
                st.download_button(
                    "Download Invoice PDF",
                    pdf,
                    f"{selected_order_id}.pdf",
                    "application/pdf"
                )
                session.close()

    # Analytics
    elif selected == "Analytics":
        st.markdown('<div class="main-header">Analytics</div>', unsafe_allow_html=True)
        if df.empty:
            st.info("Add orders to unlock analytics")
        else:
            df["revenue"] = df["price"] * df["qty"]
            top_products = df.groupby("product")["revenue"].sum().sort_values(ascending=False).head(10)
            fig = px.bar(top_products, x=top_products.values, y=top_products.index, orientation='h')
            st.plotly_chart(fig, use_container_width=True)

    # Export
    elif selected == "Export":
        st.markdown('<div class="main-header">Export Data</div>', unsafe_allow_html=True)
        if not df.empty:
            st.download_button(
                "📥 Download CSV",
                df.to_csv(index=False).encode('utf-8'),
                f"orders_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv"
            )
        else:
            st.info("No data to export")
