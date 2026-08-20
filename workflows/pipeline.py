from cbn.core.Network import Network
from cbn.core.Place import Place


def run_network():
    network = Network()
    network.plot()
    network.plot(include_routes=False)
    network.Analyse()


def run_place():
    Place.fill_all_latlng()
    Place.remove_grid_duplicates()
    Place.analyze_coverage()
    Place.open_random_uncovered_cells_in_google_maps(limit=10)


if __name__ == "__main__":
    run_place()
    run_network()
