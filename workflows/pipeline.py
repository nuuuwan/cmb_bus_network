from cbn.core.Place import Place

if __name__ == "__main__":
    Place.fill_all_latlng()

    for place in Place.list():
        print(place.name, place.get_gnd().name)

    Place.analyze_coverage()
