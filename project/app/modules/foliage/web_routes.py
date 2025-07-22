# Third party imports
from flask import jsonify, render_template, request, url_for
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.core.controller import login_required
from app.core.models import get_clients_for_user

# Local application imports
from . import foliage as web
from .controller import (
    CommonAnalysisView,
    CropView,
    FarmView,
    LeafAnalysisView,
    LotCropView,
    LotView,
    NutrientApplicationView,
    NutrientView,
    ObjectiveView,
    ProductContributionView,
    ProductionView,
    ProductPriceView,
    ProductView,
    SoilAnalysisView,
)
from .models import CommonAnalysis, Crop, Farm, Lot, LotCrop, Nutrient, Product


def get_dashboard_menu():
    """Define el menu superior en los templates"""
    return {
        "menu": [
            {"name": "Home", "url": url_for("core.index")},
            {"name": "Logout", "url": url_for("core.logout")},
            {"name": "Profile", "url": url_for("core.profile")},
        ]
    }


# 👌
@web.route("/nutrientes")
@login_required
def nutrientes():
    """
    Página: Renderiza la vista de nutrientes
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de nutrientes",
        "description": "Administración de nutrientes.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    nutrient_view = NutrientView()
    response = nutrient_view._get_nutrient_list()
    items = response.get_json()
    status_code = response.status_code
    assigned_org = get_clients_for_user(user_id)
    org_dict = {org.name: org.id for org in assigned_org}
    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "nutrients.j2",
            items=items,
            org_dict=org_dict,
            **context,
            request=request,
        ),
        200,
    )


# 👌
@web.route("/farms")
@login_required
def amd_farms():
    """
    Página: Renderiza la vista de Fincas
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de Fincas",
        "description": "Administración de Fincas.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    farm_view = FarmView()
    filter_value = request.args.get("filter_value", type=int)
    search = request.args.get("search")
    response = farm_view._get_farm_list(filter_by=filter_value, search=search)
    items = response.get_json()
    status_code = response.status_code
    assigned_org = get_clients_for_user(user_id)
    org_dict = {org.name: org.id for org in assigned_org}
    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "farms.j2",
            items=items,
            org_dict=org_dict,
            **context,
            request=request,
            filter_field="org_id",
            filter_options=assigned_org,
            filter_value=filter_value,
            select_url=url_for("foliage.amd_farms"),
            search=search,
            search_url=url_for("foliage.amd_farms"),
        ),
        200,
    )


# 👌
@web.route("/lots")
@login_required
def amd_lots(filter_value=None):
    """
    Página: Renderiza la vista de lotes
    """
    context = {
        "dashboard": True,
        "title": "Gestión de lotes",
        "description": "Administración de lotes.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    lot_view = LotView()
    filter_value = request.args.get("filter_value", type=int)
    search = request.args.get("search")
    if filter_value or search:
        response = lot_view._get_lot_list(filter_by=filter_value, search=search)
    else:
        response = lot_view._get_lot_list()

    items = response.get_json()
    status_code = response.status_code
    filter_field = "farm_id"
    farms = Farm.query.all()
    filter_options = farms
    select_url = url_for("foliage.amd_lots")
    if filter_value:
        filter_value = int(filter_value)
        farms = Farm.query.filter_by(id=filter_value).all()
    farms_dic = {farm.name: farm.id for farm in farms}
    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "lots.j2",
            items=items,
            farms_dic=farms_dic,
            **context,
            request=request,
            filter_field=filter_field,
            filter_options=filter_options,
            filter_value=filter_value,
            select_url=select_url,
            search=search,
            search_url=url_for("foliage.amd_lots"),
        ),
        200,
    )


# 👌
@web.route("/crops")
@login_required
def amd_crops():
    """
    Página: Renderiza la vista de cultivos
    """
    context = {
        "dashboard": True,
        "title": "Gestión de cultivos",
        "description": "Administración de cultivos.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    crop_view = CropView()
    response = crop_view._get_crop_list()
    items = response.get_json()
    status_code = response.status_code

    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "crops.j2",
            items=items,
            **context,
            request=request,
        ),
        200,
    )


# 👌
@web.route("/lot_crops")
@login_required
def amd_lot_crops():
    """
    Página: Renderiza la vista de lotes de cultivos
    """
    context = {
        "dashboard": True,
        "title": "Gestión de lotes de cultivos",
        "description": "Administración de lotes de cultivos.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }

    # Instanciar la vista de LotCrop
    lot_crop_view = LotCropView()

    # Obtener el valor del filtro desde los argumentos de la solicitud
    filter_value = request.args.get("filter_value")
    filter_field = "farm_id"
    farms = Farm.query.all()
    filter_options = farms

    # Obtener las relaciones LotCrop con filtro opcional por farm_id
    if filter_value:
        filter_value = int(filter_value)
        # Modificar LotCropView para aceptar un filtro por farm_id si es necesario
        # Por ahora, filtramos manualmente después de obtener la lista
        response = lot_crop_view._get_lot_crop_list()
        items = response.get_json()
        # Filtrar los items por farm_id
        items = [item for item in items if item["organization_id"] == filter_value]
        status_code = 200  # Simulamos que el filtro manual es exitoso
    else:
        response = lot_crop_view._get_lot_crop_list()
        items = response.get_json()
        status_code = response.status_code

    # Obtener lots y crops para el formulario, aplicando el filtro si existe
    if filter_value:
        lots = Lot.query.join(Farm).filter(Farm.id == filter_value).all()
    else:
        lots = Lot.query.all()
    lots_dic = {lot.name: lot.id for lot in lots}

    crops = Crop.query.all()  # Los cultivos no necesitan filtrarse por farm_id
    crop_dic = {crop.name: crop.id for crop in crops}

    if status_code != 200:
        return render_template("error.j2"), status_code

    return (
        render_template(
            "lot_crops.j2",
            items=items,
            filter_value=filter_value,
            filter_field=filter_field,
            filter_options=filter_options,
            lots_dic=lots_dic,
            crop_dic=crop_dic,
            **context,
            request=request,
        ),
        200,
    )


# 👌
@web.route("/objectives")
@login_required
def amd_objectives():
    """
    Página: Renderiza la vista de objetivos
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de objetivos",
        "description": "Administración de objetivos.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }

    # Instantiate the view and get objectives
    objective_view = ObjectiveView()
    response = objective_view._get_objective_list()
    items = response.get_json()
    status_code = response.status_code

    # Get organizations and crops for the dropdown
    assigned_org = get_clients_for_user(user_id)
    org_dict = {org.name: org.id for org in assigned_org}
    crops = Crop.query.all()
    crop_options = {crop.name: crop.id for crop in crops}

    # Define form fields
    nutrient_ids = Nutrient.query.all()
    form_fields = {
        "crop_id": {
            "type": "select",
            "label": "Cultivo",
            "options": crop_options,
            "required": True,
        },
        "target_value": {
            "type": "number",
            "label": "Valor objetivo general",
            "required": True,
            "placeholder": "Ej: 100.0",
        },
        "protein": {
            "type": "number",
            "label": "Proteína",
            "required": False,
            "placeholder": "Ej: 20.5",
        },
        "rest": {
            "type": "number",
            "label": "Descanso",
            "required": False,
            "placeholder": "Ej: 15.0",
        },
    }

    # Add nutrient fields dynamically
    for nutrient in nutrient_ids:
        form_fields[f"nutrient_{nutrient.id}"] = {
            "type": "number",
            "label": f"Valor objetivo de {nutrient.name} ({nutrient.symbol})",
            "required": False,  # Optional, as not all nutrients may be set
            "placeholder": f"Ej: 10.5 ({nutrient.unit})",
        }

    # base_headers = ["ID", "Cultivo", "Valor Objetivo", "Proteína", "Descanso", "Fecha de Creación", "Fecha de Actualización"]
    # nutrient_headers = [f"{nutrient.name} ({nutrient.symbol})" for nutrient in nutrient_ids]
    # table_headers = base_headers + nutrient_headers
    # base_fields = ["id", "crop_name", "target_value", "protein", "rest", "created_at", "updated_at"]
    # nutrient_fields = [f"nutrient_{nutrient.id}" for nutrient in nutrient_ids]
    # item_fields = base_fields + nutrient_fields

    if status_code != 200:
        return render_template("error.j2"), status_code

    return (
        render_template(
            "objectives.j2",
            items=items,
            org_dict=org_dict,
            crops=crops,  # Pass crops for reference if needed
            nutrient_ids=nutrient_ids,  # Pass nutrients for reference
            form_fields=form_fields,
            request=request,
            **context,
        ),
        200,
    )


# 👌
@web.route("/products")
@login_required
def amd_products():
    """
    Página: Renderiza la vista de productos
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de productos",
        "description": "Administración de productos.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    product_view = ProductView()
    response = product_view._get_product_list()
    items = response.get_json()
    status_code = response.status_code
    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "products.j2",
            items=items,
            **context,
            request=request,
        ),
        200,
    )


# 👌
@web.route("/product_contributions")
@login_required
def amd_product_contributions():
    """
    Página: Renderiza la vista de contribuciones de productos
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de contribuciones de productos",
        "description": "Administración de contribuciones de productos.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    # Instantiate the view and get product contributions
    product_contribution_view = ProductContributionView()
    response = product_contribution_view._get_product_contribution_list()
    items = response.get_json()
    status_code = response.status_code
    # Get products for the dropdown
    products = Product.query.all()
    product_options = {product.name: product.id for product in products}
    # Define form fields
    nutrient_ids = Nutrient.query.all()
    form_fields = {
        "product_id": {
            "type": "select",
            "label": "Producto",
            "options": product_options,
            "required": True,
        },
    }
    # Add nutrient fields dynamically
    for nutrient in nutrient_ids:
        form_fields[f"nutrient_{nutrient.id}"] = {
            "type": "number",
            "label": f"Contribución de {nutrient.name} ({nutrient.symbol})",
            "required": False,  # Optional, as not all nutrients may be set
            "placeholder": f"Ej: 10.5 ({nutrient.unit})",
        }
    # base_headers = ["ID", "Producto", "Fecha de Creación", "Fecha de Actualización"]
    # nutrient_headers = [f"{nutrient.name} ({nutrient.symbol})" for nutrient in nutrient_ids]
    # table_headers = base_headers + nutrient_headers
    # base_fields = ["id", "product_name", "created_at", "updated_at"]
    # nutrient_fields = [f"nutrient_{nutrient.id}" for nutrient in nutrient_ids]
    # item_fields = base_fields + nutrient_fields
    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "product_contributions.j2",
            items=items,
            products=products,  # Pass products for reference if needed
            nutrient_ids=nutrient_ids,  # Pass nutrients for reference
            form_fields=form_fields,
            request=request,
            **context,
        ),
        200,
    )


# 👌
@web.route("/product_prices")
@login_required
def amd_product_prices():
    """
    Página: Renderiza la vista de precios de productos
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de precios de productos",
        "description": "Administración de precios de productos.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    product_price_view = ProductPriceView()
    response = product_price_view._get_product_price_list()
    items = response.get_json()
    status_code = response.status_code
    products = Product.query.all()
    product_options = {product.name: product.id for product in products}
    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "product_prices.j2",
            items=items,
            product_options=product_options,
            **context,
            request=request,
        ),
        200,
    )


# 👌
@web.route("/common_analyses")
@login_required
def amd_common_analyses():
    """
    Página: Renderiza la vista de análisis comunes
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de análisis comunes - Bromatologico",
        "description": "Administración de análisis comunes.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    common_analysis_view = CommonAnalysisView()
    filter_value = request.args.get("filter_value")
    if filter_value:
        filter_value = int(filter_value)
        response = common_analysis_view._get_common_analysis_list(
            filter_by=filter_value
        )
    else:
        response = common_analysis_view._get_common_analysis_list()

    items = response.get_json()
    status_code = response.status_code

    # Collect the lot_ids used in the items returned so they are always available
    item_lot_ids = {item.get("lot_id") for item in items if item.get("lot_id")}

    if filter_value:
        lots = Lot.query.join(Farm).filter(Farm.id == filter_value).all()
    else:
        lots = Lot.query.all()

    # Ensure lots also include those referenced by the items
    if item_lot_ids:
        additional_lots = Lot.query.filter(Lot.id.in_(item_lot_ids)).all()
        lots_map = {lot.id: lot for lot in lots}
        for lot in additional_lots:
            lots_map[lot.id] = lot
        lots = list(lots_map.values())

    lots_dic = {lot.name: lot.id for lot in lots}

    filter_field = "farm_id"
    farms = Farm.query.all()
    filter_options = farms

    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "common_analyses.j2",
            items=items,
            lots_dic=lots_dic,
            filter_field=filter_field,
            filter_options=filter_options,
            filter_value=filter_value,
            **context,
            request=request,
        ),
        200,
    )


# 👌✍🏼
@web.route("/leaf_analyses")
@jwt_required()
def amd_leaf_analyses():
    """
    Página: Renderiza la vista de análisis de hojas
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de análisis foliares",
        "description": "Administración de análisis foliares.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }

    # Get data
    leaf_analysis_view = LeafAnalysisView()
    filter_value = request.args.get("filter_value", type=int)
    page = request.args.get("page", type=int)
    per_page = request.args.get("per_page", type=int)
    response = leaf_analysis_view._get_leaf_analysis_list(
        filter_by=filter_value, page=page, per_page=per_page
    )
    filter_field = "farm_id"
    farms = Farm.query.all()
    filter_options = farms
    data = response.get_json()
    if isinstance(data, dict) and "items" in data:
        items = data["items"]
        pagination = {
            "total": data["total"],
            "pages": data["pages"],
            "page": data["page"],
            "per_page": data["per_page"],
        }
    else:
        items = data
        pagination = None
    status_code = response.status_code

    # Get CommonAnalysisView
    analisis_comun_id = request.args.get("analisis_comun_id")
    if filter_value:
        common_analyses = (
            CommonAnalysis.query.join(Lot, CommonAnalysis.lot_id == Lot.id)
            .filter(Lot.farm_id == filter_value)
            .all()
        )
    else:
        common_analyses = CommonAnalysis.query.all()

    # Actualizar el diccionario common_analysis_options
    if analisis_comun_id:
        ca = CommonAnalysis.query.get(int(analisis_comun_id))
        if ca:
            display = f"{ca.lot.farm.name}, {ca.lot.name}, {ca.date.isoformat()}"
            common_analysis_options = {display: ca.id}
        else:
            common_analysis_options = {}
    else:
        common_analysis_options = {
            f"{ca.lot.farm.name}, {ca.lot.name}, {ca.date.isoformat()}": ca.id
            for ca in common_analyses
        }

    # Define form fields
    nutrient_ids = Nutrient.query.all()
    form_fields = {
        "common_analysis_id": {
            "type": "select",
            "label": "Análisis común",
            "options": common_analysis_options,
            "required": True,
        },
    }

    # Add nutrient fields dynamically
    for nutrient in nutrient_ids:
        form_fields[f"nutrient_{nutrient.id}"] = {
            "type": "number",
            "label": f"Valor de {nutrient.name} ({nutrient.symbol})",
            "required": False,
            "placeholder": f"Ej: 10.5 ({nutrient.unit})",
        }
    if status_code != 200:
        return render_template("error.j2"), status_code

    return (
        render_template(
            "leaf_analyses.j2",
            items=items,
            pagination=pagination,
            nutrient_ids=nutrient_ids,
            form_fields=form_fields,
            filter_field=filter_field,
            filter_options=filter_options,
            filter_value=filter_value,
            **context,
            request=request,
        ),
        200,
    )


# 👌
@web.route("/soil_analyses")
@jwt_required()
def amd_soil_analyses():
    """
    Página: Renderiza la vista de análisis de suelos
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de análisis de suelos",
        "description": "Administración de análisis de suelos.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    soil_analysis_view = SoilAnalysisView()
    filter_value = request.args.get("filter_value")
    if filter_value:
        filter_value = int(filter_value)
        response = soil_analysis_view._get_soil_analysis_list(filter_by=filter_value)
    else:
        response = soil_analysis_view._get_soil_analysis_list()

    items = response.get_json()
    status_code = response.status_code

    filter_field = "farm_id"
    farms = Farm.query.all()
    filter_options = farms

    # Get CommonAnalysisView
    analisis_comun_id = request.args.get("analisis_comun_id")
    if filter_value:
        common_analyses = (
            CommonAnalysis.query.join(Lot, CommonAnalysis.lot_id == Lot.id)
            .filter(Lot.farm_id == filter_value)
            .all()
        )
    else:
        common_analyses = CommonAnalysis.query.all()

    # Actualizar el diccionario common_analysis_options
    if analisis_comun_id:
        common_analysis_options = {int(analisis_comun_id): int(analisis_comun_id)}
    else:
        common_analysis_options = {
            common_analysis.id: common_analysis.id
            for common_analysis in common_analyses
        }

    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "soil_analyses.j2",
            items=items,
            filter_field=filter_field,
            filter_options=filter_options,
            filter_value=filter_value,
            common_analysis_options=common_analysis_options,
            **context,
            request=request,
        ),
        200,
    )


# 👌
@web.route("/nutrient_applications")
@jwt_required()
def amd_nutrient_applications():
    """
    Página: Renderiza la vista de aplicaciones de nutrientes
    """
    filter_value = request.args.get("filter_value")
    context = {
        "dashboard": True,
        "title": "Gestión de aplicaciones de nutrientes",
        "description": "Administración de aplicaciones de nutrientes.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }

    nutrient_application_view = NutrientApplicationView()
    if filter_value:
        filter_value = int(filter_value)
        response = nutrient_application_view._get_nutrient_application_list(
            filter_by=filter_value
        )
    else:
        response = nutrient_application_view._get_nutrient_application_list()

    status_code = response.status_code
    items = response.get_json()

    if status_code != 200:
        return render_template("error.j2"), status_code

    lots = (
        Lot.query.join(Farm).filter(Farm.org_id == filter_value).all()
        if filter_value
        else Lot.query.all()
    )
    lots_dic = {lot.name: lot.id for lot in lots}

    filter_field = "farm_id"
    farms = Farm.query.all()
    filter_options = farms

    # Define form fields
    nutrient_ids = Nutrient.query.all()
    form_fields = {
        "date": {"type": "date", "label": "Fecha de aplicación", "required": True},
        "lot_id": {
            "type": "select",
            "label": "Lote",
            "options": lots_dic,
            "required": True,
            "new_value": False,
        },
    }

    # Add nutrient fields dynamically
    for nutrient in nutrient_ids:
        form_fields[f"nutrient_{nutrient.id}"] = {
            "type": "number",
            "label": f"Valor de {nutrient.name} ({nutrient.symbol})",
            "required": False,
            "placeholder": f"Ej: 10.5 ({nutrient.unit})",
        }

    return (
        render_template(
            "nutrient_applications.j2",
            items=items,
            lots_dic=lots_dic,
            filter_field=filter_field,
            filter_options=filter_options,
            filter_value=filter_value,
            form_fields=form_fields,
            **context,
            request=request,
        ),
        status_code,
    )


@web.route("/productions")
@jwt_required()
def amd_productions():
    """
    Página: Renderiza la vista de producciones
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de producciones",
        "description": "Administración de producciones.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    production_view = ProductionView()
    response = production_view._get_production_list()
    items = response.get_json()
    status_code = response.status_code

    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "productions.j2",
            items=items,
            **context,
            request=request,
        ),
        200,
    )
